from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.http import request
import re
import math
import logging
import requests

_logger = logging.getLogger(__name__)


class HrLeaveDinas(models.Model):
    _name = "hr.leave.dinas"
    _description = "Module Dinas"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "name desc"

    name = fields.Char(string='Nomor', readonly=True, index="trigram", default=lambda self: _('New'))
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    nota_dinas_id = fields.Many2one('nota.dinas', string="Nota Dinas", domain=[('state', '=', 'done')])
    assigner_id = fields.Many2one('hr.employee', string="Pembuat Nota Dinas/Pemohon")
    assignee_id = fields.Many2one('hr.employee', string="Peserta")
    assignee_ids = fields.Many2many('hr.employee', 'hr_employee_assignee_ids_rel', 'leave_dinas_id', 'employee_id', string="Peserta Dinas")
    pemberi_undangan_id = fields.Many2one('hr.employee', string='Pemberi Undangan - archived')
    pemberi_undangan = fields.Text('Pemberi Undangan')
    is_pemberi_undangan = fields.Boolean(compute='_compute_is_pemberi_undangan')
    agenda_dinas = fields.Text('Maksud Perjalanan Dinas', compute="_compute_agenda_dinas", store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_gm_sppd_approval', 'Menunggu Approval SPPD oleh GM (Cabang)'),
        ('waiting_dirut_sppd_approval_from_gm', 'Menunggu Approval SPPD oleh Dirut (Cabang)'),
        ('sppd_approved_input_biaya', 'SPPD Disetujui, Input Biaya (Cabang)'),
        ('waiting_for_review_biaya', 'Menunggu Review Biaya'),
        ('review_biaya_done', 'Review Biaya Selesai'),
        ('running', 'Running'),
        ('pause', 'Pause'),
        ('done', 'Selesai'),
        ('cancel', 'Cancel'),
    ], string='Status', default='draft', track_visibility='onchange')
    transport = fields.Selection([
        ('kendaraan_dinas', 'Kendaraan Dinas'),
        ('kendaraan_pribadi', 'Kendaraan Pribadi')
    ], string='Transport - archived', default='kendaraan_dinas')
    transport_ids = fields.Many2many('hr.sppd.transport', string='Transport')
    branch_id = fields.Many2one('res.branch', string="Tempat Berangkat")
    destination_place = fields.Char('Tempat Tujuan', compute="_compute_destination_place", store=True)
    date_from = fields.Date("Tanggal Berangkat")
    date_to = fields.Date("Tanggal Kembali")
    date_change_dest = fields.Date("Tanggal Pindah Tujuan")
    is_pindah_tujuan = fields.Boolean()
    facility = fields.Text("Fasilitas", default="Dengan Fasilitas Sebagaimana Terlampir")
    total_biaya_dinas = fields.Monetary(string="Total Biaya Dinas", compute='_compute_total_biaya_dinas',
                                        currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Mata Uang',
                                  default=lambda self: self.env.company.currency_id.id)
    biaya_peserta_ids = fields.One2many('hr.leave.dinas.biaya', 'leave_dinas_id', string='Biaya per Peserta')
    participant_ids = fields.Many2many('hr.employee', 'hr_employee_participant_ids_rel', 'leave_dinas_id', 'employee_id', string="Pengikut", compute="_compute_participant")
    external_follower_ids = fields.One2many(
        'hr.leave.dinas.external.follower',
        'leave_dinas_id',
        string='Pengikut Eksternal'
    )
    pengikut_eksternal = fields.Boolean(string='Pengikut Eksternal')
    attachment_ids = fields.Many2many('ir.attachment', 'hr_leave_dinas_ir_attachment_rel', 'hr_leave_dinas_id', 'attachment_id', string="Attachments")

    # ================================= #
    # approval fields perpanjangan hari #
    # ================================= #
    extend_date_to = fields.Date(string="Tanggal Kembali Baru (Extend)")
    extend_reason = fields.Text(string="Alasan Perpanjangan Hari Dinas")
    extend_state = fields.Selection([
        ('waiting_mb', 'Menunggu Persetujuan Manager Bidang'),
        ('waiting_kadiv', 'Menunggu Persetujuan Kadiv'),
        ('waiting_gm_cabang_extend', 'Menunggu Persetujuan GM Cabang'),
        ('waiting_dirop', 'Menunggu Persetujuan Direktur Operasional'),
        ('waiting_dirkeu', 'Menunggu Persetujuan Direktur Keuangan'),
        ('waiting_dirut', 'Menunggu Persetujuan Direktur Utama'),
        ('approved', 'Disetujui'),
        ('rejected', 'Ditolak'),
        ('cancelled', 'Dibatalkan'),
    ], string="Status Perpanjangan", tracking=True)

    is_cabang_sppd = fields.Boolean(
        string="SPPD Kantor Cabang?",
        compute='_compute_is_cabang_sppd',
        store=True
    )

    extend_approval_ids = fields.One2many('hr.leave.dinas.extend.approval', 'leave_dinas_id',
                                          string="Approval Perpanjangan Hari")

    unexpected_cost_ids = fields.One2many(
        'hr.leave.dinas.unexpected.cost',
        'leave_dinas_id',
        string='Biaya Tak Terduga'
    )

    @api.constrains('date_from', 'date_to')
    def _check_tanggal_dinas(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_("Tanggal kembali harus setelah tanggal berangkat."))

    @api.depends('nota_dinas_id')
    def _compute_destination_place(self):
        for rec in self:
            rec.destination_place = rec.nota_dinas_id.destination_place

    @api.depends('pemberi_undangan_id')
    def _compute_is_pemberi_undangan(self):
        for record in self:
            employee = self.env.user.employee_id
            record.is_pemberi_undangan = record.pemberi_undangan_id == employee

    @api.depends('nota_dinas_id')
    def _compute_agenda_dinas(self):
        for rec in self:
            rec.agenda_dinas = rec.nota_dinas_id.agenda_desc

    @api.depends('nota_dinas_id')
    def _compute_participant(self):
        self.mapped('nota_dinas_id.nota_dinas_line_ids')
        for rec in self:
            if rec.nota_dinas_id:
                part = rec.nota_dinas_id.nota_dinas_line_ids.mapped('applicant_id')
                rec.participant_ids = [(6, 0, part.ids[1:])] if part else [(6, 0, [])]
            else:
                rec.participant_ids = [(6, 0, [])]

    @api.depends('nota_dinas_id.type_nodin')
    def _compute_is_cabang_sppd(self):
        for rec in self:
            if rec.nota_dinas_id and rec.nota_dinas_id.type_nodin:
                rec.is_cabang_sppd = (rec.nota_dinas_id.type_nodin == 'kantor_cabang')
            else:
                rec.is_cabang_sppd = False

    def _get_multiplier_from_satuan(self, satuan, durasi_hari):
        satuan = (satuan or '').lower().strip()

        if 'perjalanan' in satuan:
            return 1

        time_units = {
            'hari': 1,
            'minggu': 7,
            'bulan': 30,
            'tahun': 365,
        }

        satuan = re.sub(r'[^a-zA-Z0-9\s]', '', satuan).lower().strip()
        match = re.search(r'(\d+)\s*(hari|minggu|bulan|tahun)', satuan)
        if match:
            interval = int(match.group(1))
            unit = match.group(2)
            days_per_interval = interval * time_units.get(unit, 1)
            return math.ceil(durasi_hari / days_per_interval) if days_per_interval else 1

        for unit, unit_days in time_units.items():
            if unit in satuan:
                return math.ceil(durasi_hari / unit_days)

        return durasi_hari

    @api.depends('biaya_peserta_ids.amount_total')
    def _compute_total_biaya_dinas(self):
        for rec in self:
            rec.total_biaya_dinas = sum(rec.biaya_peserta_ids.mapped('amount_total'))

    def generate_sppd_sequence(self):
        angka_sequence = self.env['ir.sequence'].next_by_code('hr.leave.dinas')
        roman_months = {1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII', 8: 'VIII', 9: 'IX', 10: 'X', 11: 'XI', 12: 'XII'}
        current_month = datetime.now().month
        current_month_roman = roman_months.get(current_month, 'I')
        tahun = datetime.now().year
        bulan = datetime.now().strftime('%m')
        full_sequence = f"SPD/{tahun}/{bulan}/{current_month_roman}/{angka_sequence}"
        return full_sequence

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.generate_sppd_sequence()
        if vals.get('nota_dinas_id'):
            nota_dinas = self.env['nota.dinas'].browse(vals['nota_dinas_id'])
            if nota_dinas:
                part_ids = nota_dinas.nota_dinas_line_ids.mapped('applicant_id.id')[1:]
                vals.update({'participant_ids': [(6, 0, part_ids)]})
        res = super(HrLeaveDinas, self).create(vals)
        for rec in res:
            rec.state = 'draft'
        peserta_ids = [res.assigner_id.id] + res.participant_ids.ids
        for emp in peserta_ids:
            self.env['hr.leave.dinas.biaya'].create({
                'leave_dinas_id': res.id,
                'employee_id': emp,
            })
        return res

    def _get_sppd_approvers(self, role_code):
        dept = self.env['hr.department'].search([('biaya_sppd_role', '=', role_code)], limit=1)
        return dept.penanggung_jawab_ids or dept.manager_id

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Hanya bisa submit jika status masih Draft.'))
            rec._compute_is_cabang_sppd()

            if rec.is_cabang_sppd:
                pemohon_sppd = rec.assigner_id
                if not pemohon_sppd or not pemohon_sppd.hr_branch_id:
                    raise UserError(_("Pemohon SPPD atau branch pemohon tidak valid."))

                gm_cabang_pemohon = pemohon_sppd.hr_branch_id.manager_id

                if pemohon_sppd == gm_cabang_pemohon and gm_cabang_pemohon:  # The applicant is the GM of the branch
                    rec.state = 'waiting_dirut_sppd_approval_from_gm'  # To the Dirut to approve SPPD
                    rec.message_post(body=_(
                        "SPPD Kantor Cabang diajukan oleh GM (%s) dan menunggu approval SPPD oleh Direktur Utama.") % pemohon_sppd.name)
                else:  # The applicant is an ordinary staff member at the Branch
                    rec.state = 'waiting_gm_sppd_approval'
                    rec.message_post(body=_("SPPD Kantor Cabang telah disubmit dan menunggu approval SPPD oleh GM."))
            else:  # Head Office or other type
                rec.state = 'waiting_for_review_biaya'
                rec.message_post(body=_("SPPD (Non-Cabang) telah disubmit dan menunggu review biaya."))

    def _cron_update_sppd_states(self):
        today = fields.Date.today()
        sppds = self.search([
            ('state', 'in', ['review_biaya_done', 'running']),
            ('date_from', '!=', False),
            ('date_to', '!=', False)
        ])

        for sppd in sppds:
            if sppd.state == 'review_biaya_done' and sppd.date_from and sppd.date_from <= today:
                sppd.state = 'running'

            date_done = sppd.date_to
            if sppd.state == 'running' and date_done and date_done <= today:
                sppd.state = 'done'

    def action_check_extend_done(self):
        for rec in self:
            has_waiting = any(a.state == 'waiting' for a in rec.extend_approval_ids)
            all_approved = all(a.state == 'approved' for a in rec.extend_approval_ids)

            if not has_waiting and all_approved:
                rec.date_to = rec.extend_date_to
                rec.extend_state = 'approved'
                rec.state = 'running'
                rec.message_post(body=_(
                    "Perpanjangan hari dinas telah disetujui oleh seluruh pihak. Tanggal kembali diperbarui menjadi %s."
                ) % rec.date_to.strftime('%d-%m-%Y'))

                # Reset data perpanjangan
                rec.extend_date_to = False
                rec.extend_reason = False
                rec.extend_state = False

    def _get_expected_approver_employee_ids(self):
        emp = self.assigner_id
        if not emp or not emp.department_id:
            return []

        current_dept = emp.department_id.sudo()

        approvers = []
        if current_dept.department_type == 'bidang':
            if current_dept.manager_id:
                approvers.append(current_dept.manager_id.id)
            else:
                return []
            if current_dept.parent_id and current_dept.parent_id.manager_id:
                approvers.append(current_dept.parent_id.manager_id.id)
            else:
                return []
        elif current_dept.department_type == 'divisi':
            if current_dept.manager_id:
                approvers.append(current_dept.manager_id.id)
            else:
                return []

        return approvers

    def _check_sppd_direksi_permission(self, expected_role):
        """
        Helper method untuk mengecek apakah user saat ini memiliki role direksi tertentu
        berdasarkan keterangan_jabatan_id.nodin_workflow.
        Mirip dengan _check_direksi_permission di nota.dinas, tapi disesuaikan untuk SPPD jika perlu.
        Parameter expected_role: 'dirut', 'dirkeu', 'dirop'.
        """
        self.ensure_one()
        current_employee = self.env.user.employee_id
        if not current_employee:
            return False

        # Pastikan field 'keterangan_jabatan_id' ada di hr.employee
        if not hasattr(current_employee, 'keterangan_jabatan_id') or not current_employee.keterangan_jabatan_id:
            _logger.warning(
                "Field 'keterangan_jabatan_id' tidak ditemukan atau kosong pada employee %s (user: %s) untuk validasi direksi SPPD.",
                current_employee.name, self.env.user.login)
            return False

        keterangan_jabatan = current_employee.keterangan_jabatan_id

        # Pastikan field 'nodin_workflow' ada di model keterangan_jabatan_id
        if not hasattr(keterangan_jabatan, 'nodin_workflow'):
            _logger.warning(
                "Field 'nodin_workflow' tidak ditemukan pada model %s (Keterangan Jabatan ID: %s) untuk validasi direksi SPPD.",
                keterangan_jabatan._name, keterangan_jabatan.id)
            return False

        return keterangan_jabatan.nodin_workflow == expected_role

    def action_gm_approve_sppd(self):
        self.ensure_one()
        if not self.is_cabang_sppd or self.state != 'waiting_gm_sppd_approval':
            raise UserError(_("Aksi ini hanya valid untuk SPPD Kantor Cabang yang menunggu approval SPPD oleh GM."))

        # Approver Validation: GM of the SPPD applicant branch
        # Assume GM is the manager of hr.branch where the applicant (assigner_id) works.
        current_employee = self.env.user.employee_id
        if not current_employee:
            raise UserError(_("User Anda tidak terhubung dengan data Employee. Tidak dapat melakukan approval."))

        pemohon_branch = self.assigner_id.hr_branch_id
        if not pemohon_branch:
            raise UserError(_("Pemohon SPPD (%s) tidak terdaftar di kantor cabang manapun.") % (self.assigner_id.name))
        if pemohon_branch.location != 'branch_office':
            raise UserError(
                _("SPPD ini tidak teridentifikasi sebagai SPPD Kantor Cabang (Branch Office)."))

        branch_manager = pemohon_branch.manager_id
        if not branch_manager:
            raise UserError(_("General Manager untuk kantor cabang (%s) pemohon (%s) belum diatur di master Branch.")
                            % (pemohon_branch.name, self.assigner_id.name))

        if current_employee != branch_manager:
            raise UserError(_("Anda (%s) bukan General Manager (%s) yang ditugaskan untuk kantor cabang ini.")
                            % (current_employee.name, branch_manager.name))

        self.state = 'sppd_approved_input_biaya'
        self.message_post(body=_(
            "SPPD Kantor Cabang telah disetujui oleh General Manager (%s). Silakan input rincian biaya."
        ) % current_employee.name)

    def action_dirut_approve_sppd_from_gm(self):
        """
        Aksi untuk Direktur Utama menyetujui SPPD Kantor Cabang
        yang diajukan oleh GM Cabang itu sendiri.
        """
        self.ensure_one()

        # 1. Validasi Tipe SPPD dan State
        if not self.is_cabang_sppd or self.state != 'waiting_dirut_sppd_approval_from_gm':
            raise UserError(
                _("Aksi ini hanya valid untuk SPPD Kantor Cabang yang menunggu approval SPPD oleh Direktur Utama (diajukan GM)."))

        # 2. Validasi Pemohon adalah GM (opsional, karena state sudah menyiratkan)
        # pemohon_sppd = self.assigner_id
        # gm_cabang_pemohon = pemohon_sppd.hr_branch_id.manager_id if pemohon_sppd.hr_branch_id else False
        # if not (pemohon_sppd == gm_cabang_pemohon and gm_cabang_pemohon):
        #     raise UserError(_("SPPD ini tidak diajukan oleh GM Cabang yang sesuai."))

        # 3. Validasi Approver adalah Dirut
        current_employee = self.env.user.employee_id
        if not current_employee:
            raise UserError(_("User Anda tidak terhubung dengan data Employee. Tidak dapat melakukan approval."))

        if not self._check_sppd_direksi_permission('dirut'):
            raise UserError(
                _("Anda (%s) tidak memiliki wewenang sebagai Direktur Utama untuk menyetujui SPPD ini.") % current_employee.name)

        # 4. Lolos Validasi -> Ubah Status
        self.state = 'sppd_approved_input_biaya'
        self.message_post(body=_(
            "SPPD Kantor Cabang (diajukan GM) telah disetujui oleh Direktur Utama (%s). Silakan input rincian biaya."
        ) % current_employee.name)

    def action_submit_biaya_sppd(self):
        self.ensure_one()
        if not self.is_cabang_sppd or self.state != 'sppd_approved_input_biaya':
            raise UserError(
                _("Aksi ini hanya valid untuk SPPD Kantor Cabang yang sudah disetujui GM dan siap untuk submit biaya."))

        if not self.biaya_peserta_ids:
            raise UserError(
                _("Belum ada rincian biaya yang diinput untuk peserta manapun. Harap input biaya terlebih dahulu."))

        self.state = 'waiting_for_review_biaya'
        self.message_post(body=_(
            "Rincian biaya SPPD Kantor Cabang telah disubmit. Menunggu review & approval biaya oleh GM Cabang."
        ))


class HrLeaveDinasBiaya(models.Model):
    _name = 'hr.leave.dinas.biaya'
    _description = 'Biaya Per Peserta Dinas'

    leave_dinas_id = fields.Many2one('hr.leave.dinas', string='Referensi SPPD', ondelete='cascade')
    is_sppd_cabang = fields.Boolean(compute='_compute_is_sppd_cabang')
    employee_id = fields.Many2one('hr.employee', string='Peserta Dinas', required=True)
    biaya_header_id = fields.Many2one('hr.dinas.biaya.header', string='Template Biaya')
    amount_total = fields.Monetary(string='Total Biaya', compute='_compute_total_biaya', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Mata Uang',
                                  default=lambda self: self.env.company.currency_id.id)
    approval_mb_umum = fields.Boolean(string="Approved by MB Umum", default=False)
    approval_kadiv_sdm_umum = fields.Boolean(string="Approved by Kadiv SDM dan Umum", default=False)
    approval_mb_keuangan = fields.Boolean(string="Approved by MB Keuangan", default=False)
    approval_kadiv_keuangan = fields.Boolean(string="Approved by Kadiv Keuangan", default=False)
    approval_mb_keuangan_transfer_biaya = fields.Boolean(string="Menunggu Biaya ditransfer", default=False)
    approval_gm_cabang = fields.Boolean(string="Approved by GM Cabang", default=False)
    approval_stage = fields.Selection([
        ('draft', 'Draft'),
        # State untuk Cabang
        ('waiting_gm_biaya_cabang', 'Menunggu Approval Biaya GM Cabang'),
        # Bisa jadi 'draft' saja cukup jika _compute benar
        ('waiting_kadiv_keu_pusat_transfer', 'Menunggu Transfer Kadiv Keu. Pusat'),
        # State untuk Pusat (mungkin bisa direuse sebagian atau perlu nama beda)
        ('waiting_mb_umum', 'Menunggu Approval MB Umum (Pusat)'),  # Bisa jadi 'draft' saja cukup
        ('waiting_kadiv_sdm_umum', 'Menunggu Approval Kadiv SDM & Umum (Pusat)'),
        ('waiting_mb_keuangan_pusat', 'Menunggu Approval MB Keuangan (Pusat)'),
        ('waiting_kadiv_keuangan_pusat', 'Menunggu Approval Kadiv Keuangan (Pusat)'),
        # State Bersama
        ('waiting_for_transfer_biaya', 'Menunggu Biaya Ditransfer'),
        # Mungkin ini bisa jadi state setelah Kadiv Keu Pusat (Cabang) atau Kadiv Keu (Pusat)
        ('biaya_transfered', 'Biaya Ditransfer'),
        ('done', 'Selesai'),
    ], string="Tahap Approval Biaya", compute='_compute_approval_stage', store=True)
    approval_kadiv_keu_transfer_cabang = fields.Boolean(
        string="Approved/Transferred by Kadiv Keu. Pusat (Cabang)",
        default=False,
        copy=False
    )
    biaya_line_ids = fields.One2many('hr.leave.dinas.biaya.line', 'dinas_biaya_id', string='Rincian Biaya')

    @api.depends('leave_dinas_id.nota_dinas_id.type_nodin')
    def _compute_is_sppd_cabang(self):
        for rec in self:
            sppd = rec.leave_dinas_id
            if sppd and sppd.nota_dinas_id:
                if sppd.nota_dinas_id.type_nodin == 'kantor_cabang':
                    rec.is_sppd_cabang = True
                else:
                    rec.is_sppd_cabang = False
            else:
                rec.is_sppd_cabang = False

    @api.onchange('biaya_header_id')
    def _onchange_biaya_header_id(self):
        for rec in self:
            if rec.biaya_header_id:
                rec.biaya_line_ids = [(5, 0, 0)] + [
                    (0, 0, {
                        'komponen_id': line.komponen_id.id,
                        'jenis_lokasi': line.jenis_lokasi,
                        'golongan': line.golongan,
                        'jumlah': line.jumlah,
                        'satuan': line.satuan,
                        'currency_id': line.currency_id.id,
                    }) for line in rec.biaya_header_id.biaya_line_ids
                ]

    @api.depends('biaya_line_ids.jumlah', 'biaya_line_ids.satuan', 'leave_dinas_id.date_from', 'leave_dinas_id.date_to')
    def _compute_total_biaya(self):
        for rec in self:
            total = 0
            durasi = 1
            if rec.leave_dinas_id.date_from and rec.leave_dinas_id.date_to:
                durasi = (rec.leave_dinas_id.date_to - rec.leave_dinas_id.date_from).days or 1

            for line in rec.biaya_line_ids:
                if line.komponen_id.is_laundry and durasi <= 1:
                    continue
                multiplier = rec.leave_dinas_id._get_multiplier_from_satuan(line.satuan, durasi)
                total += line.jumlah * multiplier

            rec.amount_total = total

    @api.depends(
        'is_sppd_cabang', 'approval_gm_cabang', 'approval_kadiv_keu_transfer_cabang',  # Cabang
        'approval_mb_umum', 'approval_kadiv_sdm_umum',  # Pusat
        'approval_mb_keuangan', 'approval_kadiv_keuangan',  # Mungkin bersama atau perlu flag cabang/pusat
        'approval_mb_keuangan_transfer_biaya'  # Mungkin bersama
    )
    def _compute_approval_stage(self):
        for rec in self:
            if rec.is_sppd_cabang:
                # --- ALUR CABANG ---
                if rec.approval_kadiv_keu_transfer_cabang:  # Jika sudah ditransfer/diapprove Kadiv Keu Pusat
                    # Apakah MB Keu Pusat juga melakukan transfer fisik? Atau Kadiv Keu ini sudah termasuk transfer?
                    # Kita asumsikan setelah Kadiv Keu. Pusat approve/transfer, langsung 'biaya_transfered'
                    rec.approval_stage = 'biaya_transfered'
                elif rec.approval_gm_cabang:
                    rec.approval_stage = 'waiting_kadiv_keu_pusat_transfer'
                else:
                    rec.approval_stage = 'draft'  # Atau 'waiting_gm_biaya_cabang'
            else:
                # --- ALUR PUSAT (EXISTING YANG PERLU DISESUAIKAN) ---
                if rec.approval_mb_keuangan_transfer_biaya:
                    rec.approval_stage = 'biaya_transfered'
                elif rec.approval_kadiv_keuangan:
                    # Jika MB Keu. Pusat juga transfer untuk Cabang, maka field approval_mb_keuangan_transfer_biaya bisa dipakai bersama
                    rec.approval_stage = 'waiting_for_transfer_biaya'  # Ini menunggu MB Keu untuk transfer
                elif rec.approval_mb_keuangan:
                    rec.approval_stage = 'waiting_kadiv_keuangan_pusat'  # State 'stage_4'
                elif rec.approval_kadiv_sdm_umum:
                    rec.approval_stage = 'waiting_mb_keuangan_pusat'  # State 'stage_3'
                elif rec.approval_mb_umum:
                    rec.approval_stage = 'waiting_kadiv_sdm_umum'  # State 'stage_2'
                else:
                    rec.approval_stage = 'draft'  # Atau 'waiting_mb_umum'

    def action_submit_to_mb_umum(self):
        for rec in self:
            rec.approval_stage = 'waiting_mb_umum'

    def action_approve_mb_umum(self):
        self.ensure_one()
        if self.is_sppd_cabang:
            raise UserError(_("Aksi ini tidak berlaku untuk SPPD Kantor Cabang."))

        user_emp = self.env.user.employee_id

        # Validasi user harus penanggung jawab MB Umum
        mb_umum_dept = self.env['hr.department'].search([('department_type','=','bidang'),('biaya_sppd_role', '=', 'mb_umum')], limit=1)
        if not mb_umum_dept:
            raise ValidationError(_("Tidak ditemukan konfigurasi department yang sesuai. Silahkan hubungi Administrator."))
        if user_emp not in mb_umum_dept.manager_id:
            raise UserError(_('Anda bukan Manager Bidang Umum.'))

        if self.approval_mb_umum:
            raise UserError(_('Biaya ini sudah disetujui oleh MB Umum.'))

        self.approval_mb_umum = True
        self.leave_dinas_id.message_post(
            body=_("Biaya untuk peserta <b>%s</b> telah disetujui oleh MB Umum.") % (self.employee_id.name)
        )

    def action_approve_kadiv_sdm_umum(self):
        self.ensure_one()
        if self.is_sppd_cabang:
            raise UserError(_("Aksi ini tidak berlaku untuk SPPD Kantor Cabang."))

        user_emp = self.env.user.employee_id

        kadiv_sdm_dept = self.env['hr.department'].search([
            ('department_type', '=', 'divisi'),
            ('biaya_sppd_role', '=', 'kadiv_sdm_umum')
        ], limit=1)
        if not kadiv_sdm_dept:
            raise ValidationError(_("Tidak ditemukan konfigurasi department yang sesuai. Silahkan hubungi Administrator."))
        if user_emp != kadiv_sdm_dept.manager_id:
            raise UserError(_('Anda bukan Kadiv SDM dan Umum.'))

        if self.approval_kadiv_sdm_umum:
            raise UserError(_('Biaya ini sudah disetujui oleh Kadiv SDM dan Umum.'))

        self.approval_kadiv_sdm_umum = True
        self.leave_dinas_id.message_post(
            body=_("Biaya untuk peserta <b>%s</b> telah disetujui oleh Kadiv SDM dan Umum.") % (self.employee_id.name)
        )

    def action_approve_mb_keuangan(self):
        self.ensure_one()
        if self.is_sppd_cabang:
            raise UserError(_("Aksi ini tidak berlaku untuk SPPD Kantor Cabang."))

        user_emp = self.env.user.employee_id

        mb_keuangan_dept = self.env['hr.department'].search([
            ('department_type', '=', 'bidang'),
            ('biaya_sppd_role', '=', 'mb_keuangan')
        ], limit=1)
        if not mb_keuangan_dept:
            raise ValidationError(_("Tidak ditemukan konfigurasi department yang sesuai. Silahkan hubungi Administrator."))
        if user_emp != mb_keuangan_dept.manager_id:
            raise UserError(_('Anda bukan MB Keuangan.'))

        if self.approval_mb_keuangan:
            raise UserError(_('Biaya ini sudah disetujui oleh MB Keuangan.'))

        self.approval_mb_keuangan = True
        self.leave_dinas_id.message_post(
            body=_("Biaya untuk peserta <b>%s</b> telah disetujui oleh MB Keuangan.") % (self.employee_id.name)
        )

    def action_approve_kadiv_keuangan(self):
        self.ensure_one()
        if self.is_sppd_cabang:
            raise UserError(_("Aksi ini tidak berlaku untuk SPPD Kantor Cabang."))

        user_emp = self.env.user.employee_id

        kadiv_keuangan_dept = self.env['hr.department'].search([
            ('department_type', '=', 'divisi'),
            ('biaya_sppd_role', '=', 'kadiv_keuangan')
        ], limit=1)
        if not kadiv_keuangan_dept:
            raise ValidationError(_("Tidak ditemukan konfigurasi department yang sesuai. Silahkan hubungi Administrator."))
        if user_emp != kadiv_keuangan_dept.manager_id:
            raise UserError(_('Anda bukan Kadiv Keuangan.'))

        if self.approval_kadiv_keuangan:
            raise UserError(_('Biaya ini sudah disetujui oleh Kadiv Keuangan.'))

        self.approval_kadiv_keuangan = True
        self.leave_dinas_id.message_post(
            body=_("Biaya untuk peserta <b>%s</b> telah disetujui oleh Kadiv Keuangan.") % (self.employee_id.name)
        )

    def action_transfer_biaya_mb_keuangan(self):
        self.ensure_one()
        if self.is_sppd_cabang:
            raise UserError(_("Aksi ini tidak berlaku untuk SPPD Kantor Cabang."))

        user_emp = self.env.user.employee_id

        mb_keuangan_dept = self.env['hr.department'].search([
            ('department_type', '=', 'bidang'),
            ('biaya_sppd_role', '=', 'mb_keuangan')
        ], limit=1)
        if not mb_keuangan_dept:
            raise ValidationError(_("Tidak ditemukan konfigurasi department yang sesuai. Silahkan hubungi Administrator."))
        if user_emp != mb_keuangan_dept.manager_id:
            raise UserError(_('Anda bukan MB Keuangan dan tidak berhak melakukan transfer biaya.'))

        if self.approval_mb_keuangan_transfer_biaya:
            raise UserError(_('Biaya sudah ditransfer oleh MB Keuangan.'))

        self.approval_mb_keuangan_transfer_biaya = True
        self.leave_dinas_id.message_post(
            body=_("Biaya untuk peserta <b>%s</b> telah ditransfer oleh MB Keuangan.") % (self.employee_id.name)
        )

    def action_approve_gm_biaya_cabang(self):
        """Aksi untuk approval biaya oleh GM Cabang."""
        self.ensure_one()  # Pastikan hanya dijalankan untuk satu record biaya

        # 1. Validasi Tipe SPPD (harus Kantor Cabang)
        sppd = self.leave_dinas_id
        if not sppd.nota_dinas_id or sppd.nota_dinas_id.type_nodin != 'kantor_cabang':
            # Jika tidak ada Nota Dinas terkait atau tipenya bukan Cabang
            # Mungkin perlu fallback atau error spesifik jika SPPD bisa dibuat tanpa Nodin
            # Untuk saat ini, kita anggap SPPD Cabang selalu dari Nodin Cabang
            raise UserError(_("Approval GM Cabang hanya berlaku untuk SPPD dari Nota Dinas Kantor Cabang."))

        # 2. Validasi Status Awal (Harus dari Draft/Initial state)
        # Kita anggap 'draft' adalah state awal sebelum ada approval apapun
        # Nanti _compute_approval_stage perlu disesuaikan
        is_approved_pusat = self.approval_mb_umum or self.approval_kadiv_sdm_umum or \
                            self.approval_mb_keuangan or self.approval_kadiv_keuangan or \
                            self.approval_mb_keuangan_transfer_biaya
        if self.approval_gm_cabang or is_approved_pusat:
            raise UserError(_("Biaya ini sudah diproses atau bukan giliran approval GM Cabang."))

        # 3. Validasi Approver (GM Cabang)
        # Asumsi: GM Cabang adalah manager dari hr.branch tempat peserta (employee_id) bekerja
        current_employee = self.env.user.employee_id
        if not current_employee:
            raise UserError(_("User Anda tidak terhubung dengan data Employee. Tidak dapat melakukan approval."))

        # Cek branch peserta biaya ini
        peserta_branch = self.employee_id.hr_branch_id
        if not peserta_branch:
            raise UserError(_("Peserta (%s) tidak terdaftar di kantor cabang manapun.") % (self.employee_id.name))
        if peserta_branch.location != 'branch_office':
            # Safety check, harusnya tidak terjadi jika SPPD nya tipe Cabang
            raise UserError(
                _("Peserta (%s) tidak terdaftar di kantor cabang (Branch Office).") % (self.employee_id.name))

        branch_manager = peserta_branch.manager_id
        if not branch_manager:
            raise UserError(
                _("General Manager untuk kantor cabang (%s) belum diatur di master Branch.") % (peserta_branch.name))

        # Cek apakah user saat ini adalah GM Cabang yang dimaksud
        if current_employee != branch_manager:
            raise UserError(
                _("Anda (%s) bukan General Manager (%s) yang ditugaskan untuk kantor cabang peserta ini (%s).")
                % (current_employee.name, branch_manager.name, peserta_branch.name))

        # 4. Lolos Validasi -> Set Flag Approval
        self.approval_gm_cabang = True
        sppd.message_post(body=_(
            "Biaya untuk peserta <b>%s</b> telah disetujui oleh General Manager Cabang (%s)."
        ) % (self.employee_id.name, current_employee.name))

    def action_kadiv_keu_pusat_transfer_biaya_cabang(self):
        """
        Aksi untuk Kadiv Keuangan Kantor Pusat melakukan approval akhir dan/atau
        menandai biaya SPPD Kantor Cabang sebagai siap/sudah ditransfer.
        """
        self.ensure_one()

        # 1. Validasi Tipe SPPD (harus Kantor Cabang)
        if not self.is_sppd_cabang:  # Menggunakan field compute yang sudah ada
            raise UserError(_("Aksi ini hanya berlaku untuk biaya SPPD dari Kantor Cabang."))

        # 2. Validasi Status Sebelumnya
        #    Harus sudah diapprove oleh GM Cabang
        if not self.approval_gm_cabang:
            raise UserError(_("Biaya ini belum disetujui oleh GM Cabang."))
        #    Dan belum diproses oleh Kadiv Keu. Pusat sebelumnya
        if self.approval_kadiv_keu_transfer_cabang:
            raise UserError(_("Biaya ini sudah diproses oleh Kadiv Keuangan Kantor Pusat."))

        #    Opsional: Validasi berdasarkan approval_stage jika sudah diimplementasikan dengan benar
        #    if self.approval_stage != 'waiting_kadiv_keu_pusat_transfer':
        #        raise UserError(_("Biaya ini tidak dalam status menunggu approval/transfer Kadiv Keu. Pusat."))

        # 3. Validasi Approver adalah Kadiv Keuangan Kantor Pusat
        current_employee = self.env.user.employee_id
        if not current_employee:
            raise UserError(_("User Anda tidak terhubung dengan data Employee. Tidak dapat melakukan approval."))

        # Cari departemen Kadiv Keuangan Kantor Pusat
        # Asumsi hr.department punya field 'branch_id' (Many2one ke hr.branch)
        kadiv_keu_dept_pusat = self.env['hr.department'].search([
            ('biaya_sppd_role', '=', 'kadiv_keuangan'),  # Role yang sudah ada
            ('department_type', '=', 'divisi'),  # Sesuai instruksi loe
            ('branch_id.location', '=', 'head_office')  # Harus dari Head Office
        ], limit=1)

        if not kadiv_keu_dept_pusat:
            raise UserError(
                _("Tidak ditemukan konfigurasi Departemen Divisi di Kantor Pusat untuk role 'Kadiv Keuangan'. Harap hubungi Administrator."))

        approver_kadiv_keu_pusat = kadiv_keu_dept_pusat.manager_id
        if not approver_kadiv_keu_pusat:
            raise UserError(_("Manager untuk Departemen %s (role Kadiv Keuangan - Pusat) belum diatur.")
                            % (kadiv_keu_dept_pusat.name))

        if current_employee != approver_kadiv_keu_pusat:
            raise UserError(
                _("Anda (%s) bukan Kadiv Keuangan Kantor Pusat (%s) yang berwenang untuk aksi ini.")
                % (current_employee.name, approver_kadiv_keu_pusat.name))

        # 4. Lolos Validasi -> Set Flag Approval/Transfer
        self.approval_kadiv_keu_transfer_cabang = True
        self.leave_dinas_id.message_post(body=_(
            "Biaya untuk peserta <b>%s</b> (SPPD Cabang) telah disetujui/diproses transfer oleh Kadiv Keuangan Kantor Pusat (%s)."
        ) % (self.employee_id.name, current_employee.name))

    def action_mark_biaya_done(self):
        self.ensure_one()
        if self.approval_stage != 'biaya_transfered':
            raise UserError(_('Biaya ini belum mencapai tahap transfer.'))

        self.approval_stage = 'done'

        # Pastikan approval stage semua data biaya peserta sudah done untuk trigger status SPPD menjadi review_biaya_done
        all_done = all(
            biaya.approval_stage in ['done']
            for biaya in self.leave_dinas_id.biaya_peserta_ids
        )
        if all_done:
            self.leave_dinas_id.state = 'review_biaya_done'
            self.leave_dinas_id.message_post(
                body=_("Seluruh biaya peserta telah selesai di-review.")
            )


class HrLeaveDinasBiayaLine(models.Model):
    _name = 'hr.leave.dinas.biaya.line'
    _description = 'Rincian Biaya Per Peserta Dinas'

    dinas_biaya_id = fields.Many2one('hr.leave.dinas.biaya', string='Referensi Biaya Peserta', ondelete='cascade')
    komponen_id = fields.Many2one('dinas.komponen', string='Komponen', required=True)
    jenis_lokasi = fields.Selection([
        ('ibu_kota', 'Ibu Kota Provinsi'),
        ('non_ibu_kota', 'Non Ibu Kota Provinsi'),
    ])
    golongan = fields.Selection([
        ('direksi', 'Dewan Komisaris / Direksi'),
        ('ks', 'KS/KDIV/VP/Setingkat/GM'),
        ('manager_bidang', 'Manager Bidang'),
        ('manager_sub', 'Manager Sub Bidang / Manager Unit'),
        ('staf', 'Staf'),
    ])
    jumlah = fields.Monetary(string='Jumlah (Rp)')
    satuan = fields.Char(string='Satuan',
                         help='Format satuan biaya. Contoh yang valid: "Rp / Hari", "Rp / 7 Hari", "Rp / 3 Bulan", atau "Rp / Perjalanan".')
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id.id)

    @api.constrains('satuan')
    def _check_valid_satuan(self):
        allowed_keywords = ['hari', 'minggu', 'bulan', 'tahun', 'perjalanan']
        for rec in self:
            if rec.satuan:
                satuan_bersih = re.sub(r'[^a-zA-Z0-9\s]', '', rec.satuan).lower()
                if not any(kw in satuan_bersih for kw in allowed_keywords):
                    raise UserError(_(
                        "Satuan '%s' pada komponen '%s' tidak dikenali.\n"
                        "Gunakan satuan seperti: 'Rp / Hari', 'Rp / 7 Hari', 'Rp / Bulan', dst."
                    ) % (rec.satuan, rec.komponen_id.name or 'Tanpa Nama'))


class HrLeaveDinasExtendApproval(models.Model):
    _name = 'hr.leave.dinas.extend.approval'
    _description = 'Approval Perpanjangan Hari Dinas'
    _order = 'sequence asc'

    leave_dinas_id = fields.Many2one('hr.leave.dinas', string='SPPD', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Approver', required=True)
    state = fields.Selection([
        ('waiting', 'Menunggu Persetujuan'),
        ('approved', 'Disetujui'),
        ('rejected', 'Ditolak'),
    ], string='Status', default='waiting')
    sequence = fields.Integer(string='Urutan', default=10)
    is_director = fields.Boolean(string='Direksi')
    approval_type = fields.Selection([
        ('mb', 'Manager Bidang'),
        ('kadiv', 'Kadiv'),
        ('gm_cabang_extend', 'GM Cabang (Perpanjangan)'),
        ('dirop', 'Direktur Operasional'),
        ('dirkeu', 'Direktur Keuangan'),
        ('dirut', 'Direktur Utama'),
    ], string='Jenis')
    is_my_turn = fields.Boolean(string='Saya Approver Aktif', compute='_compute_is_my_turn')

    @api.depends('state', 'leave_dinas_id.extend_approval_ids.state')
    def _compute_is_my_turn(self):
        current_uid = self.env.uid
        for rec in self:
            is_turn = False
            if rec.state == 'waiting' or rec.employee_id.user_id.id == current_uid:
                approvals = rec.leave_dinas_id.extend_approval_ids.sorted(key=lambda a: a.sequence)
                for approval in approvals:
                    if approval.state == 'waiting':
                        is_turn = approval.id == rec.id
                        break
            rec.is_my_turn = is_turn

    def _validate_current_user_as_approver(self):
        """Validasi umum apakah user saat ini adalah approver yang ditugaskan."""
        self.ensure_one()
        if not self.employee_id:
            raise UserError(_('Data approver di baris persetujuan ini kosong. Harap hubungi Administrator.'))

        current_user_employee = self.env.user.employee_id
        if not current_user_employee:
            raise UserError(_('User Anda tidak terhubung dengan data Employee. Tidak dapat melakukan aksi.'))

        if self.employee_id != current_user_employee:
            raise UserError(_('Anda (%s) bukan approver (%s) yang ditugaskan untuk tahap ini.')
                            % (current_user_employee.name, self.employee_id.name))

        if self.state != 'waiting':
            raise UserError(_('Permintaan persetujuan ini sudah diproses sebelumnya (%s).') % self.state)

    def action_approve(self):
        self.ensure_one()
        self._validate_current_user_as_approver()  # Panggil validasi umum

        # Validasi spesifik berdasarkan approval_type (jika ada)
        # Untuk 'gm_cabang_extend', employee_id sudah di-set oleh wizard sebagai GM Cabang yang benar.
        # Untuk 'dirut', employee_id sudah di-set oleh wizard sebagai Dirut yang benar.
        # Validasi struktur organisasi terkini untuk MB/Kadiv Pusat:
        if self.approval_type in ['mb', 'kadiv']:
            # _get_expected_approver_employee_ids ada di hr.leave.dinas (SPPD)
            # Ini untuk memastikan jika ada perubahan struktur, user yg approve masih sah
            valid_approver_ids = self.leave_dinas_id._get_expected_approver_employee_ids()
            if self.env.user.employee_id.id not in valid_approver_ids and self.employee_id.id not in valid_approver_ids:  # Double check
                # Bisa jadi self.employee_id adalah yg lama, dan user yg login adalah penggantinya
                # Atau self.employee_id adalah yg baru, tapi user yg login bukan dia
                # Untuk simpelnya, kita cek user yg login saja
                if self.env.user.employee_id.id not in valid_approver_ids:
                    raise UserError(
                        _('Struktur organisasi telah berubah. Anda tidak lagi tercatat sebagai approver (%s) yang sah untuk SPPD ini.') % self.get_approval_type_display())

        # Validasi giliran (jika ada multiple approvers dalam satu SPPD extend request)
        # Untuk skenario Cabang, hanya ada 1 approver (GM atau Dirut) jadi ini tidak terlalu kritikal,
        # tapi untuk Pusat yang berjenjang, ini penting.
        approvals_sorted = self.leave_dinas_id.extend_approval_ids.sorted(key=lambda a: a.sequence)
        for approval_item in approvals_sorted:
            if approval_item.state == 'waiting':
                if approval_item.id != self.id:  # Jika ada yang lain sebelum dia masih waiting
                    raise UserError(
                        _('Bukan giliran Anda untuk menyetujui. Persetujuan saat ini menunggu dari %s (%s).')
                        % (approval_item.employee_id.name, approval_item.get_approval_type_display()))
                break  # Jika ini yang pertama waiting, maka giliran dia

        # --- Lolos semua validasi ---
        self.state = 'approved'

        # Update SPPD utama (hr.leave.dinas)
        sppd = self.leave_dinas_id
        sppd.message_post(body=_(
            "<b>%s</b> telah MENYETUJUI perpanjangan hari dinas. (Tahap: <i>%s</i>)"
        ) % (self.employee_id.name, self.get_approval_type_display()))  # Gunakan display name

        # Cek apakah ada approver selanjutnya atau semua sudah approve
        next_approver_record = next((a for a in approvals_sorted if a.id != self.id and a.state == 'waiting'),
                                    None)  # Cari yang lain yg masih waiting

        if next_approver_record:
            sppd.extend_state = f'waiting_{next_approver_record.approval_type}'
            # Pesan di chatter SPPD sudah ter-post di atas
        else:
            # Tidak ada approver lain yang waiting, berarti semua sudah approve
            sppd.action_check_extend_done()  # Panggil method di SPPD untuk finalisasi

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_reject(self):
        self.ensure_one()
        self._validate_current_user_as_approver()  # Panggil validasi umum

        # Validasi spesifik (sama seperti di action_approve jika perlu)
        if self.approval_type in ['mb', 'kadiv']:
            valid_approver_ids = self.leave_dinas_id._get_expected_approver_employee_ids()
            if self.env.user.employee_id.id not in valid_approver_ids:
                raise UserError(
                    _('Struktur organisasi telah berubah. Anda tidak lagi tercatat sebagai approver (%s) yang sah untuk SPPD ini.') % self.get_approval_type_display())

        # Validasi giliran
        approvals_sorted = self.leave_dinas_id.extend_approval_ids.sorted(key=lambda a: a.sequence)
        for approval_item in approvals_sorted:
            if approval_item.state == 'waiting':
                if approval_item.id != self.id:
                    raise UserError(
                        _('Bukan giliran Anda untuk menolak. Persetujuan saat ini menunggu dari %s (%s).')
                        % (approval_item.employee_id.name, approval_item.get_approval_type_display()))
                break

        # --- Lolos semua validasi ---
        self.state = 'rejected'

        sppd = self.leave_dinas_id
        sppd.extend_state = 'rejected'  # Set status perpanjangan di SPPD utama jadi ditolak
        sppd.state = 'running'  # Kembalikan status SPPD utama ke 'running' (atau state sebelum 'pause')

        sppd.message_post(body=_(
            "<b>%s</b> telah MENOLAK permintaan perpanjangan hari dinas. (Tahap: <i>%s</i>)"
        ) % (self.employee_id.name, self.get_approval_type_display()))

        # Reset data perpanjangan di SPPD utama (opsional, bisa juga tidak direset agar ada histori)
        # Jika mau direset:
        # sppd.extend_date_to = False
        # sppd.extend_reason = False
        # sppd.extend_approval_ids.unlink() # Hapus semua baris approval jika ditolak (hati-hati) #
        # Atau biarkan saja, extend_state = 'rejected' sudah cukup menandakan.

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def get_approval_type_display(self):
        """Helper untuk mendapatkan display name dari approval_type."""
        self.ensure_one()
        return dict(self._fields['approval_type'].selection).get(self.approval_type, self.approval_type)


class HrLeaveDinasUnexpectedCost(models.Model):
    _name = 'hr.leave.dinas.unexpected.cost'
    _description = 'Biaya Tak Terduga Dinas'
    _order = 'id desc'

    leave_dinas_id = fields.Many2one(
        'hr.leave.dinas',
        string='Referensi SPPD',
        ondelete='cascade',
        required=True
    )
    name = fields.Char(string='Keterangan Biaya', required=True)
    amount = fields.Monetary(string='Jumlah Biaya', required=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Mata Uang',
        default=lambda self: self.env.company.currency_id.id
    )