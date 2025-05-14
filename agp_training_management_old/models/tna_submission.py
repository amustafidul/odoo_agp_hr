# agp_training_management/models/tna_submission.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class TnaSubmission(models.Model):
    _name = 'tna.submission'
    _description = 'TNA Submission Form (by Dept/Branch)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc, name'

    name = fields.Char(
        string='Nomor Usulan TNA',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: 'Baru'
    )
    period_id = fields.Many2one(
        'tna.period',
        string='Periode TNA',
        required=True,
        ondelete='restrict',
        tracking=True,
        domain="[('state', '=', 'open')]"
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Divisi Pengusul',
        required=True,
        tracking=True
    )
    branch_id = fields.Many2one(
        'res.branch',
        string='Cabang Pengusul',
        required=True,
        tracking=True,
        domain="[('company_id', '=', company_id)]"
    )
    company_id = fields.Many2one(
        'res.company',
        string='Perusahaan',
        related='period_id.company_id',
        store=True,
        readonly=True
    )
    user_id = fields.Many2one(
        'res.users',
        string='Diajukan Oleh (User)',
        default=lambda self: self.env.user,
        tracking=True,
        readonly=True,
        states={'draft': [('readonly', False)]}
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Penanggung Jawab (Pegawai)',
        tracking=True,
        domain="[('user_id', '=', user_id)]",
        help="Pegawai yang bertanggung jawab atas usulan ini (Kadiv/GM)."
    )
    submission_date = fields.Datetime(
        string='Tanggal Pengajuan ke SDM',
        readonly=True,
        copy=False,
        tracking=True
    )
    gm_approval_user_id = fields.Many2one(
        'res.users',
        string='Disetujui oleh GM (User)',
        tracking=True,
        copy=False
    )
    gm_approval_date = fields.Date(
        string='Tanggal Persetujuan GM',
        tracking=True,
        copy=False
    )
    proposed_training_ids = fields.One2many(
        'tna.proposed.training',
        'submission_id',
        string='Detail Usulan Kebutuhan Training',
        states={'submitted': [('readonly', True)], 'processed': [('readonly', True)]}
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Diajukan ke SDM'),
        # ('under_review_sdm', 'Ditinjau SDM'),
        ('processed', 'Selesai Diproses SDM')
    ],
        string='Status Usulan',
        default='draft',
        copy=False,
        tracking=True,
        group_expand='_read_group_status_ids'
    )
    notes_kadiv_gm = fields.Text(
        string='Catatan Pengusul (Kadiv/GM)',
        states={'submitted': [('readonly', True)], 'processed': [('readonly', True)]}
    )
    notes_sdm = fields.Text(string='Catatan Review SDM')

    total_proposed_trainings = fields.Integer(
        compute='_compute_total_proposed_trainings',
        string='Jumlah Usulan Training',
        store=True
    )
    total_estimated_cost = fields.Monetary(
        compute='_compute_total_estimated_cost',
        string='Total Estimasi Biaya',
        currency_field='currency_id',
        store=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Currency',
        readonly=True
    )

    @api.model
    def create(self, vals):
        if vals.get('name', 'Baru') == 'Baru':
            # Generate sequence number, misal: TNA-SUB/2025/05/001
            # Ambil tahun dan bulan dari period_id jika ada, atau tanggal create
            period = self.env['tna.period'].browse(vals.get('period_id')) if vals.get('period_id') else None
            if period and period.date_start_submission:
                date_ref = period.date_start_submission
            else:
                date_ref = fields.Date.context_today(self)

            sequence_code = 'tna.submission.sequence'
            vals['name'] = self.env['ir.sequence'].next_by_code(sequence_code) or 'Baru'
        return super(TnaSubmission, self).create(vals)

    @api.depends('proposed_training_ids')
    def _compute_total_proposed_trainings(self):
        for submission in self:
            submission.total_proposed_trainings = len(submission.proposed_training_ids)

    @api.depends('proposed_training_ids.estimated_cost')
    def _compute_total_estimated_cost(self):
        for submission in self:
            submission.total_estimated_cost = sum(pt.estimated_cost for pt in submission.proposed_training_ids)

    @api.model
    def _read_group_status_ids(self, states, domain, order):
        status_list = [key for key, val in self._fields['state'].selection]
        return status_list

    # --- Tombol Aksi Workflow ---
    def action_submit_to_sdm(self):
        for submission in self:
            if not submission.proposed_training_ids:
                raise UserError("Harap isi minimal satu detail usulan training sebelum mengajukan.")
            if any(line.state == 'new' for line in submission.proposed_training_ids):
                # Set semua line item menjadi 'pending_approval'
                submission.proposed_training_ids.filtered(lambda l: l.state == 'new').write(
                    {'state': 'pending_approval'})

            submission.write({
                'state': 'submitted',
                'submission_date': fields.Datetime.now()
            })
            # Kirim notifikasi ke grup SDM (jika ada)
            # self.activity_schedule('mail.mail_activity_data_todo', user_id=period_id.responsible_user_id.id) # Contoh
            # atau post message ke channel SDM

    def action_mark_processed_by_sdm(self):
        # Validasi: Cek apakah semua proposed_training_ids sudah di-approve atau reject
        for submission in self:
            if any(line.state == 'pending_approval' for line in submission.proposed_training_ids):
                raise UserError("Masih ada usulan training yang belum direview (approve/reject).")
            submission.state = 'processed'
            # Bisa juga cek apakah periodenya sudah 'processing'
            if submission.period_id and submission.period_id.state != 'processing':
                submission.period_id.action_start_processing()

    def action_reset_to_draft(self):
        # Hanya bisa dilakukan jika belum ada line item yang di-approve/reject oleh SDM
        # atau oleh user tertentu (misal SDM atau admin)
        for submission in self:
            if any(line.state not in ['new', 'pending_approval'] for line in submission.proposed_training_ids):
                # Jika ada yg sudah approved/rejected, mungkin perlu konfirmasi lebih atau hak akses khusus
                # raise UserError("Tidak bisa di-reset ke draft jika ada usulan yang sudah diproses SDM (approved/rejected).")
                pass  # Untuk sekarang, biarkan bisa di-reset, tapi perlu perhatian
            submission.write({'state': 'draft'})
            submission.proposed_training_ids.write({'state': 'new'})  # Kembalikan status line juga
            submission.submission_date = False

    @api.constrains('period_id', 'department_id', 'branch_id')
    def _check_unique_submission_per_period_dept_branch(self):
        for record in self:
            # Memastikan satu departemen/cabang hanya bisa submit satu form TNA untuk periode yang sama
            # Ini opsional, tergantung kebijakan. Jika boleh submit > 1, hapus constraint ini.
            existing = self.search_count([
                ('id', '!=', record.id),
                ('period_id', '=', record.period_id.id),
                ('department_id', '=', record.department_id.id),
                ('branch_id', '=', record.branch_id.id)
            ])
            if existing > 0:
                raise ValidationError(
                    f"Usulan TNA untuk Divisi '{record.department_id.name}' dan Cabang '{record.branch_id.name}' pada periode '{record.period_id.name}' sudah ada.")