from odoo import models, fields, api
from odoo.exceptions import UserError


class TrainingCourse(models.Model):
    _name = 'training.course'
    _description = 'Pelaksanaan/Realisasi Training'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(
        string="Nama Training/Diklat Final",
        required=True,
        tracking=True,
        index="trigram"
    )
    originating_tna_id = fields.Many2one(
        'tna.proposed.training',
        string='Asal Usulan TNA',
        readonly=True,
        copy=False,
        ondelete='restrict',
        help="Usulan TNA yang menjadi dasar pelaksanaan training ini."
    )
    state = fields.Selection([
        ('draft', 'Draft Pelaksanaan'),
        ('registered', 'Didaftarkan'),
        ('paid', 'Sudah Dibayar'),
        ('ongoing', 'Sedang Berlangsung'),
        ('completed', 'Training Selesai'),
        ('cancelled', 'Dibatalkan')
        ],
        string='Status Pelaksanaan',
        default='draft',
        copy=False,
        tracking=True,
        index=True,
        group_expand='_read_group_state_ids'
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Mata Uang',
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    training_scope_id = fields.Many2one('tna.training.scope', string='Lingkup Diklat')
    description = fields.Text(string='Deskripsi Training Final')
    employee_ids = fields.Many2many('hr.employee', string="Peserta Final Training")
    budgeted_cost = fields.Monetary(string="Biaya Estimasi/Budget (dari TNA)", currency_field='currency_id')
    organizer = fields.Char(string="Penyelenggara Usulan/Final")
    branch_id = fields.Many2one('res.branch', string="Cabang")
    department_id = fields.Many2one('hr.department', string="Divisi Pengusul Awal")
    company_id = fields.Many2one(
        'res.company',
        string="Perusahaan",
        default=lambda self: self.env.company,
        required=True,
        readonly=True
    )
    actual_start_date = fields.Date(string="Tanggal Mulai Aktual", tracking=True)
    actual_end_date = fields.Date(string="Tanggal Selesai Aktual", tracking=True)
    actual_duration_days = fields.Integer(string="Durasi Aktual (Hari)", compute='_compute_actual_duration_days', store=True)
    actual_duration_hours = fields.Integer(string="Durasi Aktual (Jam)", tracking=True)

    training_location_type = fields.Selection([
        ('offline', 'Offline'),
        ('online', 'Online'),
        ('blended', 'Blended/Hybrid')
        ], string="Tipe Lokasi Training", tracking=True)
    training_location_detail = fields.Char(string="Detail Lokasi/Platform Training", tracking=True)

    actual_cost = fields.Monetary(string="Biaya Realisasi", currency_field='currency_id', tracking=True)

    final_organizer_vendor_id = fields.Many2one('res.partner', string="Vendor/Penyelenggara Final", domain="[('is_company','=',True)]")
    rkap_link_notes = fields.Text(string="Catatan Keterkaitan dengan RKAP")

    certificate_received = fields.Boolean(string="Sertifikat Diterima?", tracking=True)
    certificate_number = fields.Char(string="Nomor Sertifikat", tracking=True)
    certificate_issue_date = fields.Date(string="Tanggal Terbit Sertifikat", tracking=True)
    certificate_expiry_date = fields.Date(string="Tanggal Kadaluarsa Sertifikat", tracking=True)

    evaluation_ids = fields.One2many('training.evaluation', 'course_id', string="Evaluasi Training")
    evaluation_count = fields.Integer(string="Jumlah Evaluasi", compute='_compute_evaluation_count')

    @api.model
    def _read_group_state_ids(self, states, domain, order):
        state_list = [key_val[0] for key_val in self._fields['state'].selection]
        return state_list

    @api.depends('actual_start_date', 'actual_end_date')
    def _compute_actual_duration_days(self):
        for rec in self:
            if rec.actual_start_date and rec.actual_end_date:
                delta = rec.actual_end_date - rec.actual_start_date
                rec.actual_duration_days = delta.days + 1
            else:
                rec.actual_duration_days = 0

    def _compute_evaluation_count(self):
        for record in self:
            try:
                record.evaluation_count = self.env['training.evaluation'].search_count([('course_id', '=', record.id)])
            except KeyError:
                record.evaluation_count = 0


    # --- Tombol Aksi Workflow untuk Realisasi ---
    # Akan kita buat nanti (action_register, action_mark_paid, action_start_training, action_complete_training, action_cancel)

    # --- Method action_view_evaluations (dari modul lama) ---
    # Ini akan kita pindahkan/adaptasi nanti saat memproses training_evaluation.py
    # Untuk sekarang, cukup kerangka modelnya dulu.

    # --- HAPUS METHOD LAMA dari agp_training_ib.training_course.py ---
    # Seperti action_submit, action_set_to_draft (yang untuk alur permohonan lama)
    # Dan create_training_evaluation (logika ini akan pindah ke cron atau model evaluation)
    # Juga _compute_training_year, _compute_training_date_range, _compute_duration (yang lama)
    # _compute_evaluation_count bisa dipertahankan jika field evaluation_ids dan modelnya sudah ada.
    # action_generate_sample_data juga bisa dihapus atau diadaptasi.

    def action_set_state_completed(self):
        self.ensure_one()

        res = self.write({'state': 'completed'})

        if res and self.state == 'completed':
            CompletedTraining = self.env['hr.employee.completed.training']
            for employee in self.employee_ids:
                existing_completed_training = CompletedTraining.search([
                    ('employee_id', '=', employee.id),
                    ('realization_id', '=', self.id)
                ], limit=1)

                if not existing_completed_training:
                    CompletedTraining.create({
                        'employee_id': employee.id,
                        'realization_id': self.id,
                        # Field related akan otomatis terisi dari realization_id
                        # 'notes': 'Dibuat otomatis dari penyelesaian training.' # Opsional
                    })

            TrainingEvaluation = self.env['training.evaluation']
            for employee in self.employee_ids:
                existing_evaluation = TrainingEvaluation.search([
                    ('employee_id', '=', employee.id),
                    ('course_id', '=', self.id)
                ], limit=1)

                if not existing_evaluation:
                    # Siapkan nilai default untuk evaluasi
                    # default_get dari training.evaluation akan mengisi evaluation_line_ids
                    eval_vals = TrainingEvaluation.default_get(TrainingEvaluation.fields_get_keys())

                    eval_vals.update({
                        'employee_id': employee.id,
                        'course_id': self.id,
                        'branch_id': employee.hr_branch_id.id if employee.hr_branch_id else (
                            self.branch_id.id if self.branch_id else False),
                        'training_date_from': self.actual_start_date,
                        'training_date_to': self.actual_end_date,
                        'training_organizer': self.organizer,
                        'supervisor_id': employee.parent_id.id if employee.parent_id else False,
                        # 'status': 'draft',
                    })
                    TrainingEvaluation.create(eval_vals)

        return res

    def action_register(self):
        self.write({'state': 'registered'})

    def action_mark_paid(self):
        self.write({'state': 'paid'})

    def action_start_training(self):
        if not self.actual_start_date:
            raise UserError("Harap isi Tanggal Mulai Aktual sebelum memulai training.")
        self.write({'state': 'ongoing'})

    def action_complete_training(self):
        if not self.actual_end_date:
            raise UserError("Harap isi Tanggal Selesai Aktual sebelum menyelesaikan training.")
        if self.actual_start_date and self.actual_end_date and self.actual_end_date < self.actual_start_date:
            raise UserError("Tanggal Selesai Aktual tidak boleh sebelum Tanggal Mulai Aktual.")
        return self.action_set_state_completed()

    def action_cancel_training(self):
        self.write({'state': 'cancelled'})
        if self.originating_tna_id and self.originating_tna_id.state == 'realized':
            self.originating_tna_id.write({'state': 'approved', 'training_realization_id': False})

    def action_reset_to_draft_realization(self):
        if self.state not in ['cancelled', 'registered']:
            raise UserError(
                "Hanya training yang statusnya Dibatalkan atau Didaftarkan (dan belum ada proses lanjut) yang bisa direset ke draft.")
        self.env['hr.employee.completed.training'].search([('realization_id', '=', self.id)]).unlink()
        self.evaluation_ids.unlink()
        self.write({'state': 'draft'})