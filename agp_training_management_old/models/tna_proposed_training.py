# agp_training_management/models/tna_proposed_training.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class TnaProposedTraining(models.Model):
    _name = 'tna.proposed.training'
    _description = 'TNA Proposed Training Line Item'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Untuk chatter jika diperlukan per item
    _order = 'submission_id, sequence, id'

    submission_id = fields.Many2one(
        'tna.submission',
        string='Form Usulan TNA',
        required=True,
        ondelete='cascade',  # Jika submission dihapus, line item ikut terhapus
        index=True
    )
    sequence = fields.Integer(string='No. Urut', default=10)  # Untuk urutan di form
    name = fields.Char(
        string='Nama Diklat/Workshop/Sertifikasi',
        required=True,
        tracking=True
    )
    training_scope_id = fields.Many2one(
        'tna.training.scope',
        string='Lingkup Diklat',
        tracking=True
        # domain Opsional jika ingin membatasi berdasarkan sesuatu
    )
    description = fields.Text(
        string='Justifikasi & Deskripsi Kebutuhan',
        help="Jelaskan mengapa pelatihan ini dibutuhkan dan apa tujuannya.",
        required=True  # Sesuai blueprint
    )
    proposed_employee_ids = fields.Many2many(
        'hr.employee',
        'tna_proposed_training_employee_rel',  # Nama tabel relasi
        'proposed_training_id',
        'employee_id',
        string='Nama Peserta Diusulkan',
        tracking=True,
        copy=True  # Salin peserta saat record di-copy
    )
    estimated_participant_count = fields.Integer(
        string='Estimasi Jumlah Peserta',
        compute='_compute_estimated_participant_count',
        store=True,  # Simpan hasilnya
        tracking=True,
        help="Jumlah peserta yang diusulkan untuk training ini."
    )
    # Untuk mengakomodasi contoh form "Waktu Pelaksanaan" yang mungkin teks bebas atau semester
    proposed_period_char = fields.Char(
        string='Periode Pelaksanaan (Usulan)',
        help="Contoh: Semester I, Kuartal 3, atau Bulan Tertentu",
        tracking=True
    )
    # Untuk mengakomodasi contoh rekap "HARI" & "JAM"
    estimated_duration_days = fields.Integer(
        string='Estimasi Durasi (Hari)',
        tracking=True
    )
    estimated_duration_hours = fields.Integer(
        string='Estimasi Durasi (Jam)',
        tracking=True
    )
    estimated_cost = fields.Monetary(
        string='Estimasi Biaya',
        currency_field='currency_id',
        tracking=True,
        required=True  # Sesuai blueprint, biaya penting
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='submission_id.currency_id',  # Ambil dari submission (yg related ke company)
        string='Currency',
        readonly=True,
        store=True  # Perlu store=True untuk field related yg dipakai di monetary
    )
    # Untuk mengakomodasi contoh form "Penyelenggara"
    proposed_organizer = fields.Char(
        string='Usulan Penyelenggara',
        tracking=True
    )
    # Field Related untuk memudahkan filtering/grouping di view tanpa perlu join kompleks
    department_id = fields.Many2one(
        'hr.department',
        related='submission_id.department_id',
        string='Divisi Pengusul',
        store=True,  # Penting untuk bisa di-group by dan filter
        index=True
    )
    branch_id = fields.Many2one(
        'res.branch',
        related='submission_id.branch_id',
        string='Cabang Pengusul',
        store=True,  # Penting untuk bisa di-group by dan filter
        index=True
    )
    period_id = fields.Many2one(
        'tna.period',
        related='submission_id.period_id',
        string='Periode TNA',
        store=True,
        index=True
    )
    state = fields.Selection([
        ('new', 'Baru Diinput'),  # Saat dibuat oleh Kadiv/GM
        ('pending_approval', 'Menunggu Approval SDM'),  # Setelah submission diajukan
        ('approved', 'Disetujui SDM'),
        ('rejected', 'Ditolak SDM'),
        ('realized', 'Sudah Dibuatkan Realisasi')  # Status tambahan setelah 'approved' dan dibuatkan realisasinya
    ],
        string='Status Usulan',
        default='new',
        copy=False,  # Jangan copy status saat record di-copy
        tracking=True,
        group_expand='_read_group_status_ids'
    )
    rejection_reason = fields.Text(string='Alasan Penolakan (oleh SDM)')
    sdm_approver_id = fields.Many2one(
        'res.users',
        string='SDM Reviewer/Approver',
        copy=False,
        tracking=True
    )
    approval_date = fields.Datetime(
        string='Tanggal Approval/Rejection',
        copy=False,
        tracking=True
    )
    # Link ke record realisasi yang akan dibuat setelah approval
    training_realization_id = fields.Many2one(
        'training.course',  # Mengarah ke model training.course yg sudah dirombak
        string='Realisasi Training Terkait',
        readonly=True,
        copy=False  # Jangan copy link ini
    )
    can_approve = fields.Boolean(compute='_compute_can_approve', string="Bisa Approve/Reject?")  # Untuk kontrol UI

    # Compute fields untuk rekap (seperti di blueprint)
    # Di sini kita tidak mengulang logicnya, tapi fieldnya perlu ada jika ingin ditampilkan
    # atau digunakan di view. Perhitungan detail bisa di-handle di report atau pivot.
    # Atau, jika ingin disimpan, perlu @api.depends yang sesuai.
    # Untuk kesederhanaan awal, kita skip dulu compute field cost_for_rekap_... di sini
    # dan fokus pada data dasar. Rekap detail akan dibuat di view/reportnya.

    @api.depends('proposed_employee_ids')
    def _compute_estimated_participant_count(self):
        for record in self:
            record.estimated_participant_count = len(record.proposed_employee_ids)

    @api.model
    def _read_group_status_ids(self, states, domain, order):
        status_list = [key for key, val in self._fields['state'].selection]
        return status_list

    def _get_sdm_training_group_users(self):
        """Helper untuk mendapatkan user di grup SDM Training."""
        # Ganti 'nama_modul.nama_grup_xml_sdm_training' dengan ID grup XML yg benar
        # Misalnya, jika grupnya 'base.group_hr_manager', atau grup custom
        # Ini contoh, perlu disesuaikan:
        try:
            group_id = self.env.ref('hr.group_hr_manager').id  # Ganti dengan grup SDM yang relevan
            return self.env['res.users'].search([('groups_id', 'in', group_id)])
        except ValueError:  # Jika grup tidak ditemukan
            return self.env['res.users']  # Kosongkan atau beri default

    # --- Tombol Aksi Workflow (oleh SDM) ---
    def action_approve(self):
        # Perlu hak akses khusus untuk tombol ini (misal grup SDM)
        for rec in self:
            if rec.state != 'pending_approval':
                raise UserError("Hanya usulan yang 'Menunggu Approval SDM' yang bisa disetujui.")

            # Membuat record di training.course (yang sudah dirombak jadi realisasi)
            # Ini bagian penting dari integrasi
            training_course_vals = {
                'name': rec.name,
                'originating_tna_id': rec.id,
                'training_scope_id': rec.training_scope_id.id if rec.training_scope_id else False,
                'description': rec.description,
                'employee_ids': [(6, 0, rec.proposed_employee_ids.ids)],  # (6,0,IDs) untuk set Many2many
                # 'planned_start_date': Isi jika ada info dari proposed_period_char atau default
                # 'planned_end_date': Isi jika ada info
                'budgeted_cost': rec.estimated_cost,
                'currency_id': rec.currency_id.id,
                'organizer': rec.proposed_organizer,  # Bisa jadi 'proposed_organizer'
                'branch_id': rec.branch_id.id,
                # Departemen bisa lebih kompleks jika peserta dari banyak dept,
                # untuk awal bisa ambil dari dept pengusul
                'department_id': rec.department_id.id,
                'status_realization': 'draft',  # Status awal di training.course (realisasi)
                # Field lain yg relevan dari rec bisa disalin
            }
            new_realization = self.env['training.course'].create(training_course_vals)

            rec.write({
                'state': 'approved',
                'sdm_approver_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
                'training_realization_id': new_realization.id  # Simpan link ke realisasi
            })

            # Kirim notifikasi ke pengusul (Kadiv/GM) bahwa usulannya disetujui
            if rec.submission_id.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',  # Activity type
                    note=f"Usulan training '{rec.name}' telah DISETUJUI dan akan diproses untuk realisasi.",
                    user_id=rec.submission_id.user_id.id
                )

    def action_reject(self):
        # Perlu hak akses khusus
        # Akan lebih baik jika ada wizard untuk mengisi alasan penolakan
        for rec in self:
            if rec.state != 'pending_approval':
                raise UserError("Hanya usulan yang 'Menunggu Approval SDM' yang bisa ditolak.")

            # Pastikan alasan penolakan diisi jika field rejection_reason jadi required saat reject
            # if not rec.rejection_reason:
            # raise UserError("Harap isi Alasan Penolakan.")

            rec.write({
                'state': 'rejected',
                'sdm_approver_id': self.env.user.id,
                'approval_date': fields.Datetime.now()
            })

            # Kirim notifikasi ke pengusul (Kadiv/GM) bahwa usulannya ditolak
            if rec.submission_id.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',  # Activity type
                    note=f"Usulan training '{rec.name}' DITOLAK. Alasan: {rec.rejection_reason or 'Tidak ada alasan spesifik'}",
                    user_id=rec.submission_id.user_id.id
                )

    def action_set_to_pending(self):
        # Untuk SDM mengembalikan ke pending jika salah approve/reject (perlu hak akses)
        self.write({
            'state': 'pending_approval',
            'sdm_approver_id': False,
            'approval_date': False,
            'rejection_reason': False,
            # Jika sudah ada training.realization_id, mungkin perlu dihapus atau di-cancel juga? Ini kompleks.
            # Untuk awal, kita tidak hapus link realisasi, tapi ini perlu jadi perhatian.
        })
        # Hapus aktivitas notifikasi sebelumnya jika ada
        self.activity_unlink(['mail.mail_activity_data_todo'])

    @api.depends('state')  # Tambahkan field lain yg relevan jika ada
    def _compute_can_approve(self):
        # Logic sederhana untuk kontrol tombol di UI
        # Ganti 'nama_modul.nama_grup_xml_sdm_training' dengan ID grup XML yg benar
        can_approve_group = self.env.user.has_group('hr.group_hr_manager')  # Contoh grup SDM
        for rec in self:
            rec.can_approve = can_approve_group and rec.state == 'pending_approval'