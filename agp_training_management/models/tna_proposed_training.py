from odoo import models, fields, api
from odoo.exceptions import UserError


class TnaProposedTraining(models.Model):
    _name = 'tna.proposed.training'
    _description = 'Detail Usulan Kebutuhan Training (Line Item)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'submission_id, sequence, id'

    submission_id = fields.Many2one(
        'tna.submission',
        string='Form Usulan TNA Induk',
        required=True,
        ondelete='cascade',
        index=True,
        help="Form usulan TNA tempat detail training ini berada."
    )
    sequence = fields.Integer(
        string='No. Urut',
        default=10,
        help="Nomor urut untuk tampilan di form usulan."
    )
    name = fields.Char(
        string='Nama Diklat/Workshop/Sertifikasi',
        required=True,
        tracking=True,
        help="Judul training yang diusulkan."
    )
    training_scope_id = fields.Many2one(
        'tna.training.scope',
        string='Lingkup Diklat/Training',
        tracking=True,
        help="Pilih lingkup atau kategori training yang sesuai."
    )
    description = fields.Text(
        string='Justifikasi & Deskripsi Kebutuhan',
        help="Jelaskan mengapa pelatihan ini dibutuhkan, apa tujuannya, dan manfaat yang diharapkan."
    )
    proposed_employee_ids = fields.Many2many(
        'hr.employee',
        'tna_proposed_training_employee_rel',
        'proposed_training_id',
        'employee_id',
        string='Nama Peserta Diusulkan',
        tracking=True,
        copy=True,
        help="Pilih karyawan yang diusulkan untuk mengikuti training ini."
    )
    estimated_participant_count = fields.Integer(
        string='Estimasi Jumlah Peserta',
        compute='_compute_estimated_participant_count',
        store=True,
        tracking=True,
        help="Jumlah peserta otomatis berdasarkan 'Nama Peserta Diusulkan'."
    )
    proposed_period_char = fields.Char(
        string='Periode Pelaksanaan (Usulan)',
        help="Contoh: Semester I 2025, Kuartal 3 2025, atau Bulan Tertentu (misal: Juni 2025)",
        tracking=True
    )
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
        required=True,
        help="Perkiraan total biaya untuk pelaksanaan training ini."
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Mata Uang',
        compute='_compute_currency_id',
        store=True,
        readonly=True
    )
    proposed_organizer = fields.Char(
        string='Usulan Penyelenggara Training',
        tracking=True
    )
    department_id = fields.Many2one(
        'hr.department',
        related='submission_id.department_id',
        string='Divisi Pengusul',
        store=True,
        index=True
    )
    branch_id = fields.Many2one(
        'res.branch',
        related='submission_id.branch_id',
        string='Cabang Pengusul',
        store=True,
        index=True
    )
    period_id = fields.Many2one(
        'tna.period',
        related='submission_id.period_id',
        string='Periode TNA',
        store=True,
        index=True
    )
    company_id = fields.Many2one(
        'res.company',
        related='submission_id.company_id',
        string='Perusahaan',
        store=True,
        readonly=True
    )
    state = fields.Selection([
        ('new', 'Baru Diinput'),
        ('pending_approval', 'Menunggu Approval SDM'),
        ('approved', 'Disetujui SDM'),
        ('rejected', 'Ditolak SDM'),
        ('realized', 'Sudah Dibuatkan Realisasi')
        ],
        string='Status Usulan Item',
        default='new',
        copy=False,
        tracking=True,
        index=True,
        group_expand='_read_group_state_ids'
    )
    rejection_reason = fields.Text(
        string='Alasan Penolakan (oleh SDM)',
        tracking=True
    )
    sdm_approver_id = fields.Many2one(
        'res.users',
        string='SDM Reviewer/Approver',
        copy=False,
        tracking=True,
        readonly=True
    )
    approval_date = fields.Datetime(
        string='Tanggal Approval/Rejection',
        copy=False,
        tracking=True,
        readonly=True
    )
    training_realization_id = fields.Many2one(
        'training.course',
        string='Link ke Realisasi Training',
        readonly=True,
        copy=False,
        ondelete='set null',
        help="Training yang direalisasikan berdasarkan usulan ini."
    )
    can_approve_or_reject = fields.Boolean(
        compute='_compute_can_approve_or_reject',
        string="Bisa Approve/Reject?"
    )

    @api.depends('proposed_employee_ids')
    def _compute_estimated_participant_count(self):
        for record in self:
            record.estimated_participant_count = len(record.proposed_employee_ids)

    @api.depends('submission_id', 'submission_id.currency_id')
    def _compute_currency_id(self):
        for rec in self:
            if rec.submission_id and rec.submission_id.currency_id:
                rec.currency_id = rec.submission_id.currency_id
            else:
                rec.currency_id = rec.company_id.currency_id or self.env.company.currency_id

    @api.onchange('submission_id')
    def _onchange_submission_id_for_related_fields_in_line(self):
        if self.submission_id:
            self.currency_id = self.submission_id.currency_id or self.company_id.currency_id or self.env.company.currency_id
            self.department_id = self.submission_id.department_id
            self.branch_id = self.submission_id.branch_id
            self.period_id = self.submission_id.period_id
            self.company_id = self.submission_id.company_id
        else:
            self.currency_id = self.env.company.currency_id
            self.department_id = False
            self.branch_id = False
            self.period_id = False
            self.company_id = self.env.company

    @api.model
    def _read_group_state_ids(self, states, domain, order):
        state_list = [key_val[0] for key_val in self._fields['state'].selection]
        return state_list

    @api.depends('state')
    def _compute_can_approve_or_reject(self):
        is_sdm_approver = self.env.user.has_group('hr.group_hr_manager')
        for rec in self:
            rec.can_approve_or_reject = is_sdm_approver and rec.state == 'pending_approval'

    def action_approve(self):
        self.ensure_one()
        if not self.can_approve_or_reject:
             raise UserError("Anda tidak memiliki hak atau usulan ini tidak dalam status yang benar untuk disetujui.")
        if self.state != 'pending_approval':
            raise UserError("Hanya usulan yang statusnya 'Menunggu Approval SDM' yang bisa disetujui.")

        training_course_vals = {
            'name': self.name,
            'originating_tna_id': self.id,
            'training_scope_id': self.training_scope_id.id if self.training_scope_id else False,
            'description': self.description,
            'employee_ids': [(6, 0, self.proposed_employee_ids.ids)],
            'budgeted_cost': self.estimated_cost,
            'currency_id': self.currency_id.id if self.currency_id else self.env.company.currency_id.id,
            'organizer': self.proposed_organizer,
            'branch_id': self.branch_id.id if self.branch_id else False,
            'department_id': self.department_id.id if self.department_id else False,
            'company_id': self.company_id.id if self.company_id else self.env.company.id,
            'state': 'draft',
            # 'planned_start_date': Bisa diisi jika proposed_period_char bisa diparsing
            # 'planned_duration_days': self.estimated_duration_days,
        }

        try:
            training_course_model = self.env['training.course']
        except KeyError:
            raise UserError("Model 'training.course' belum terdefinisi. Harap buat kerangka model tersebut terlebih dahulu.")

        new_realization_training = training_course_model.create(training_course_vals)

        self.write({
            'state': 'approved',
            'sdm_approver_id': self.env.user.id,
            'approval_date': fields.Datetime.now(),
            'training_realization_id': new_realization_training.id
        })

        if self.submission_id.user_id:
            self.activity_schedule(
                activity_type_id=self.env.ref('mail.mail_activity_data_todo').id,
                summary=f"Usulan training '{self.name}' telah DISETUJUI",
                note=f"Usulan training '{self.name}' dari form {self.submission_id.name} telah disetujui dan akan diproses untuk realisasi. ID Realisasi: {new_realization_training.name_get()[0][1] if new_realization_training else 'N/A'}",
                user_id=self.submission_id.user_id.id
            )
        return True

    def action_reject(self):
        self.ensure_one()
        if not self.can_approve_or_reject:
             raise UserError("Anda tidak memiliki hak atau usulan ini tidak dalam status yang benar untuk ditolak.")
        if self.state != 'pending_approval':
            raise UserError("Hanya usulan yang statusnya 'Menunggu Approval SDM' yang bisa ditolak.")

        # Dianjurkan menggunakan wizard untuk mengisi alasan penolakan yang proper
        # if not self.rejection_reason:
        #     raise UserError("Harap isi Alasan Penolakan sebelum menolak usulan.")

        self.write({
            'state': 'rejected',
            'sdm_approver_id': self.env.user.id,
            'approval_date': fields.Datetime.now()
            # rejection_reason diisi manual di form
        })

        # Kirim notifikasi ke pengusul
        if self.submission_id.user_id:
            self.activity_schedule(
                activity_type_id=self.env.ref('mail.mail_activity_data_todo').id,
                summary=f"Usulan training '{self.name}' DITOLAK",
                note=f"Usulan training '{self.name}' dari form {self.submission_id.name} telah ditolak. Alasan: {self.rejection_reason or 'Tidak ada alasan spesifik dari SDM.'}",
                user_id=self.submission_id.user_id.id
            )
        return True

    def action_set_to_pending_approval(self):
        """Mengembalikan state ke 'pending_approval' oleh SDM jika ada kesalahan."""
        # Tambahkan pengecekan hak akses jika perlu
        # if not self.env.user.has_group('hr.group_hr_manager'):
        #     raise UserError("Hanya SDM yang bisa melakukan aksi ini.")

        for rec in self:
            if rec.training_realization_id:
                raise UserError(f"Tidak bisa dikembalikan ke 'Pending Approval' karena sudah ada Realisasi Training ({rec.training_realization_id.name_get()[0][1]}) yang terhubung. Harap batalkan atau hapus Realisasi Training tersebut terlebih dahulu jika ingin mengubah status usulan ini.")

            rec.write({
                'state': 'pending_approval',
                'sdm_approver_id': False,
                'approval_date': False,
                'rejection_reason': False,
            })
            rec.activity_unlink(['mail.mail_activity_data_todo'])
        return True