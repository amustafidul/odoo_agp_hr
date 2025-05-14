from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, time

import logging

_logger = logging.getLogger(__name__)


class HrLeaveDinasModifyWizard(models.TransientModel):
    _name = 'hr.leave.dinas.modify.wizard'
    _description = 'Wizard Modifikasi Perjalanan Dinas'

    modification_type = fields.Selection([
        ('early_return', 'Kembali Lebih Awal'),
        ('extend_days', 'Perpanjangan Hari Dinas'),
        ('change_location', 'Pindah Lokasi'),
    ], string='Jenis Modifikasi', required=True)

    new_date_to = fields.Date('Tanggal Kembali Baru')
    new_sppd_location = fields.Char('Tujuan Baru')
    reason = fields.Text('Alasan', required=True)

    leave_dinas_id = fields.Many2one('hr.leave.dinas', string='SPPD', required=True)

    @api.onchange('modification_type')
    def _onchange_modification_type(self):
        if self.modification_type != 'early_return':
            self.new_date_to = False

    def action_apply_modification(self):
        self.ensure_one()
        sppd = self.leave_dinas_id

        if self.modification_type == 'early_return':
            if not self.new_date_to:
                raise UserError(_('Tanggal Pulang Baru wajib diisi.'))
            if self.new_date_to >= sppd.date_to:
                raise UserError(_('Tanggal pulang baru harus lebih awal dari tanggal yang sekarang.'))

            sppd.date_to = self.new_date_to
            sppd.state = 'done'
            sppd.message_post(body=_(
                "SPPD dimodifikasi: <br/>"
                "<b>Jenis</b>: Kembali Lebih Awal<br/>"
                "<b>Tanggal Pulang Baru</b>: %s<br/>"
                "<b>Alasan</b>: %s"
            ) % (self.new_date_to.strftime('%d-%m-%Y'), self.reason))


        elif self.modification_type == 'extend_days':

            # Validasi batas waktu pengajuan (deadline jam 13:00 di hari H)

            original_sppd_date_to = sppd.date_to

            now_in_user_tz = fields.Datetime.context_timestamp(self, datetime.utcnow())

            deadline_time_object = time(13, 0)  # Jam 13:00

            # Cek jika hari ini adalah hari terakhir dinas dan sudah lewat jam 13:00

            # Perlu diperhatikan, jika sppd.date_to sudah lewat beberapa hari, apakah masih boleh extend?

            # Asumsi saat ini: validasi deadline hanya berlaku jika pengajuan di hari H.

            if now_in_user_tz.date() == original_sppd_date_to and now_in_user_tz.time() > deadline_time_object:
                raise UserError(_(

                    "Pengajuan perpanjangan hari dinas hanya dapat dilakukan maksimal pukul 13:00 "

                    "di hari terakhir dinas (Tanggal SPPD berakhir: %s)."

                ) % (original_sppd_date_to.strftime('%d-%m-%Y')))

            # Validasi tanggal baru

            if not self.new_date_to:
                raise UserError(_('Tanggal Kembali Baru wajib diisi untuk perpanjangan.'))

            if self.new_date_to <= original_sppd_date_to:  # Harus lebih besar dari tanggal kembali awal

                raise UserError(_('Tanggal perpanjangan baru harus setelah tanggal kembali awal (%s).')

                                % original_sppd_date_to.strftime('%d-%m-%Y'))

            approvals = []  # List untuk menyimpan data approval yang akan dibuat

            sequence = 10  # Mulai sequence untuk approval

            next_extend_state_key = False  # Untuk menentukan state awal perpanjangan di SPPD

            # Pastikan field is_cabang_sppd sudah ter-compute di SPPD

            if 'is_cabang_sppd' not in sppd or sppd.is_cabang_sppd is None:
                sppd._compute_is_cabang_sppd()  # Panggil compute jika belum ada nilainya

            if sppd.is_cabang_sppd:

                # --- ALUR PERPANJANGAN KANTOR CABANG ---

                pemohon_sppd = sppd.assigner_id  # assigner_id adalah pemohon SPPD

                if not pemohon_sppd or not pemohon_sppd.hr_branch_id:
                    raise UserError(_("Pemohon SPPD (%s) atau data kantor cabang pemohon tidak valid.")

                                    % (pemohon_sppd.name if pemohon_sppd else 'N/A'))

                gm_cabang_pemohon = pemohon_sppd.hr_branch_id.manager_id

                if not gm_cabang_pemohon:
                    raise UserError(
                        _("General Manager untuk kantor cabang (%s) pemohon (%s) belum diatur di master Branch.")

                        % (pemohon_sppd.hr_branch_id.name, pemohon_sppd.name))

                if pemohon_sppd == gm_cabang_pemohon:

                    # KASUS 1: Pemohon adalah GM Cabang, approver perpanjangan adalah Dirut

                    dirut_employee = self.env['hr.employee'].search([

                        ('keterangan_jabatan_id.nodin_workflow', '=', 'dirut')

                    ], limit=1)

                    if not dirut_employee:
                        raise UserError(
                            _("Data Direktur Utama (dengan role 'dirut' di Keterangan Jabatan) tidak ditemukan."))

                    approvals.append((0, 0, {

                        'employee_id': dirut_employee.id,

                        'approval_type': 'dirut',  # Menggunakan tipe approval 'dirut' yang sudah ada

                        'is_director': True,

                        'sequence': sequence

                    }))

                    next_extend_state_key = 'dirut'

                    _logger.info("Perpanjangan SPPD Cabang oleh GM %s, approver: Dirut %s", pemohon_sppd.name,
                                 dirut_employee.name)

                else:

                    # KASUS 2: Pemohon adalah Staf Cabang, approver perpanjangan adalah GM Cabang

                    approvals.append((0, 0, {

                        'employee_id': gm_cabang_pemohon.id,

                        'approval_type': 'gm_cabang_extend',  # Tipe approval baru

                        'is_director': False,  # GM Cabang bukan direksi pusat

                        'sequence': sequence

                    }))

                    next_extend_state_key = 'gm_cabang_extend'

                    _logger.info("Perpanjangan SPPD Cabang oleh Staf %s, approver: GM Cabang %s", pemohon_sppd.name,
                                 gm_cabang_pemohon.name)


            else:

                # --- ALUR PERPANJANGAN KANTOR PUSAT (LOGIC EXISTING) ---

                emp_pusat = sppd.assigner_id  # Pemohon SPPD

                dept_pusat = emp_pusat.department_id

                if not dept_pusat:
                    raise UserError(
                        _('Pegawai (%s) tidak memiliki department untuk alur perpanjangan Kantor Pusat.') % emp_pusat.name)

                if dept_pusat.department_type == 'bidang':

                    if not dept_pusat.manager_id: raise UserError(
                        _('Manager Bidang belum diatur untuk departemen %s.') % dept_pusat.name)

                    approvals.append(
                        (0, 0, {'employee_id': dept_pusat.manager_id.id, 'approval_type': 'mb', 'sequence': sequence}))

                    sequence += 10

                    if not dept_pusat.parent_id or not dept_pusat.parent_id.manager_id:
                        raise UserError(_('Kadiv (atasan bidang) belum diatur untuk departemen %s.') % dept_pusat.name)

                    approvals.append((0, 0,
                                      {'employee_id': dept_pusat.parent_id.manager_id.id, 'approval_type': 'kadiv',
                                       'sequence': sequence}))

                    sequence += 10

                elif dept_pusat.department_type == 'divisi':

                    if not dept_pusat.manager_id: raise UserError(
                        _('Kadiv belum diatur untuk departemen %s.') % dept_pusat.name)

                    approvals.append((0, 0, {'employee_id': dept_pusat.manager_id.id, 'approval_type': 'kadiv',
                                             'sequence': sequence}))

                    sequence += 10

                else:

                    # Jika tidak ada atasan langsung MB/Kadiv, atau departemen tidak bertipe bidang/divisi

                    # Maka alur persetujuan akan langsung ke Direksi.

                    # Jika ini tidak diinginkan, tambahkan error di sini.

                    _logger.info(
                        "Pemohon SPPD Pusat %s dari dept %s (tipe: %s) tidak memiliki atasan MB/Kadiv, perpanjangan langsung ke Direksi.",

                        emp_pusat.name, dept_pusat.name, dept_pusat.department_type)

                # Tambahkan jajaran direksi (Kantor Pusat - Logic Existing)

                keterangan_roles_pusat = {  # Urutan ini penting untuk approval berjenjang Direksi

                    'dirop': 'Direktur Operasional',

                    'dirkeu': 'Direktur Keuangan',

                    'dirut': 'Direktur Utama',

                }

                for role_code, role_name in keterangan_roles_pusat.items():

                    keterangan_jabatan = self.env['hr.employee.keterangan.jabatan'].search([

                        ('nodin_workflow', '=', role_code)], limit=1)

                    if not keterangan_jabatan:
                        raise UserError(_('Data jabatan untuk %s belum dikonfigurasi (nodin_workflow = %s).')

                                        % (role_name, role_code.upper()))

                    director = self.env['hr.employee'].search([

                        ('keterangan_jabatan_id', '=', keterangan_jabatan.id)], limit=1)

                    if not director:
                        raise UserError(_('Pegawai untuk %s belum ditetapkan.') % role_name)

                    approvals.append((0, 0, {

                        'employee_id': director.id,

                        'approval_type': role_code,  # Menggunakan role_code (dirop, dirkeu, dirut)

                        'is_director': True,

                        'sequence': sequence

                    }))

                    sequence += 10

                if approvals:  # Tentukan next_extend_state_key dari approver pertama di list approvals

                    next_extend_state_key = approvals[0][2]['approval_type']

            if not approvals:  # Seharusnya tidak terjadi jika logic di atas benar

                raise UserError(
                    _("Tidak ada approver yang dapat ditentukan untuk perpanjangan SPPD ini. Mohon periksa konfigurasi."))

            # Simpan data permintaan perpanjangan ke SPPD

            sppd.write({

                'extend_date_to': self.new_date_to,

                'extend_reason': self.reason,

                'extend_state': f'waiting_{next_extend_state_key}' if next_extend_state_key else False,

                'state': 'pause',  # SPPD utama di-pause selama proses approval perpanjangan

                'extend_approval_ids': [(5, 0, 0)] + approvals  # Hapus approval lama (jika ada), buat yang baru

            })

            sppd.message_post(body=_("Permintaan perpanjangan hari dinas telah dibuat dan menunggu persetujuan."))

            # Notifikasi ke MB Umum (jika masih relevan untuk semua kasus, bisa dikondisikan juga)

            self._send_sppd_extension_notification_to_mb_umum(sppd)

        elif self.modification_type == 'change_location':
            if not self.new_sppd_location:
                raise UserError(_('Tujuan Baru wajib diisi.'))

            sppd.destination_place = self.new_sppd_location
            sppd.state = 'running'
            sppd.message_post(body=_(
                "SPPD dimodifikasi: <br/>"
                "<b>Jenis</b>: Pindah Lokasi Tujuan Dinas<br/>"
                "<b>Tujuan Baru</b>: %s<br/>"
                "<b>Alasan</b>: %s"
            ) % (self.new_sppd_location, self.reason))

        return {'type': 'ir.actions.act_window_close'}

    def _send_sppd_extension_notification_to_mb_umum(self, sppd_record):
        """
        Sending notification (Activity & message_post) requesting SPPD extension
        to the Manager and PJ MB Umum.
        """
        mb_umum_dept = self.env['hr.department'].search([
            ('department_type', '=', 'bidang'),
            ('biaya_sppd_role', '=', 'mb_umum')
        ], limit=1)

        if not mb_umum_dept:
            _logger.warning("Departemen MB Umum tidak ditemukan, notifikasi SPPD extend dilewati.")
            return

        recipient_employees = set()
        if mb_umum_dept.manager_id:
            recipient_employees.add(mb_umum_dept.manager_id)
        for pj_employee in mb_umum_dept.penanggung_jawab_ids:
            recipient_employees.add(pj_employee)

        if not recipient_employees:
            _logger.info("Tidak ada karyawan penerima (Manager/PJ) di departemen MB Umum untuk notifikasi SPPD extend.")
            return

        # Data preparation for activity and message_post
        user_ids_for_activity = []
        partner_ids_for_message = []
        for emp in recipient_employees:
            if emp.user_id:
                user_ids_for_activity.append(emp.user_id.id)
                if emp.user_id.partner_id:
                    partner_ids_for_message.append(emp.user_id.partner_id.id)
            else:
                _logger.warning(
                    f"Karyawan {emp.name} tidak memiliki user ID terkait, tidak bisa dikirim notifikasi/activity.")

        user_ids_for_activity = list(set(user_ids_for_activity))
        partner_ids_for_message = list(set(partner_ids_for_message))

        # Data for notification/activity
        original_end_date_str = sppd_record.date_to.strftime('%d-%m-%Y') if sppd_record.date_to else _('N/A')
        # self.new_date_to is the date submitted from the wizard
        proposed_new_end_date_str = self.new_date_to.strftime('%d-%m-%Y') if self.new_date_to else _('N/A')
        sppd_assigner_name = sppd_record.assigner_id.name or _('N/A')
        sppd_extend_reason = sppd_record.extend_reason or _('Tidak ada alasan diberikan.')

        # ---- 1. Create Mail Activity for "Bell" & "To Do" Notification ----
        if user_ids_for_activity:
            activity_type_xmlid = 'mail.mail_activity_data_todo'
            activity_type = self.env.ref(activity_type_xmlid, raise_if_not_found=False)
            activity_type_id = activity_type.id if activity_type else False

            if not activity_type_id:
                # Fallback if XML ID not found (should not happen in standard Odoo)
                activity_type_on_the_fly = self.env['mail.activity.type'].search([('name', '=', 'To Do')], limit=1)
                if activity_type_on_the_fly:
                    activity_type_id = activity_type_on_the_fly.id
                else:  # If 'To Do' doesn't exist either, create a simple activity type
                    activity_type_id = self.env['mail.activity.type'].create(
                        {'name': 'Pemberitahuan SPPD', 'delay_count': 0}).id
                    _logger.warning("Activity type 'To Do' tidak ditemukan, membuat activity type baru.")

            summary_activity = _("Review Perpanjangan SPPD: %s") % sppd_record.name
            note_activity_html = _("""
                <p>Permintaan perpanjangan SPPD <b>{sppd_name}</b> oleh <b>{assigner_name}</b>.</p>
                <ul>
                    <li>Tgl Kembali Awal: {original_date_to}</li>
                    <li>Tgl Kembali Baru Diajukan: {proposed_new_date_to}</li>
                    <li>Alasan: {extend_reason}</li>
                </ul>
                <p>Mohon untuk segera direview.</p>
            """).format(
                sppd_name=sppd_record.name,
                assigner_name=sppd_assigner_name,
                original_date_to=original_end_date_str,
                proposed_new_date_to=proposed_new_end_date_str,
                extend_reason=sppd_extend_reason
            )

            model_id_hr_leave_dinas = self.env['ir.model']._get_id('hr.leave.dinas')
            if not model_id_hr_leave_dinas:
                _logger.error("Model 'hr.leave.dinas' tidak ditemukan. Activity tidak bisa dibuat.")
                return

            for user_id_target in user_ids_for_activity:
                self.env['mail.activity'].create({
                    'activity_type_id': activity_type_id,
                    'summary': summary_activity,
                    'note': note_activity_html,
                    'res_id': sppd_record.id,
                    'res_model_id': model_id_hr_leave_dinas,
                    'user_id': user_id_target,
                    'date_deadline': fields.Date.today(),
                })
            _logger.info(
                f"Activity 'Review Perpanjangan SPPD' dibuat untuk users: {user_ids_for_activity} terkait SPPD {sppd_record.name}")

        # ---- 2. Send Message to Chatter (and Potential Email if User Prefers) ----
        if partner_ids_for_message:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            sppd_url_for_message = False
            action_xml_id = 'agp_dinas_ib.form_sppd_persetujuan_action'
            action = self.env.ref(action_xml_id, raise_if_not_found=False)
            if base_url and action:
                sppd_url_for_message = f"{base_url}/web#id={sppd_record.id}&model={sppd_record._name}&view_type=form&action={action.id}"

            subject_email = _("Info: Permintaan Perpanjangan SPPD %s") % sppd_record.name

            body_html_chatter = _("""
                <p>Yth. Bapak/Ibu,</p>
                <p>Terdapat permintaan perpanjangan untuk Surat Perintah Perjalanan Dinas (SPPD) yang membutuhkan perhatian Anda:</p>
                <ul>
                    <li><strong>Nomor SPPD:</strong> {sppd_name}</li>
                    <li><strong>Pemohon:</strong> {assigner_name}</li>
                    <li><strong>Tanggal Kembali Awal:</strong> {original_date_to}</li>
                    <li><strong>Tanggal Kembali Baru (Diajukan):</strong> {proposed_new_date_to}</li>
                    <li><strong>Alasan Perpanjangan:</strong> {extend_reason}</li>
                </ul>
                <p>{sppd_link_html}</p><p>Terima kasih.</p>
            """).format(
                sppd_name=sppd_record.name,
                assigner_name=sppd_assigner_name,
                original_date_to=original_end_date_str,
                proposed_new_date_to=proposed_new_end_date_str,
                extend_reason=sppd_extend_reason,
                sppd_link_html=f'<a href="{sppd_url_for_message}">Klik di sini untuk detail</a>.' if sppd_url_for_message else _(
                    'Buka SPPD terkait di Odoo.')
            )

            sppd_record.message_post(
                body=body_html_chatter,
                subject=subject_email,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                partner_ids=partner_ids_for_message,
                email_layout_xmlid='mail.mail_notification_light'
            )
            _logger.info(
                f"Pesan chatter & Email (jika preferensi user) terkirim ke partners: {partner_ids_for_message} untuk SPPD {sppd_record.name}")