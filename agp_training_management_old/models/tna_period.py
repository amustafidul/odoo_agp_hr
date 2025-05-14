# agp_training_management/models/tna_period.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class TnaPeriod(models.Model):
    _name = 'tna.period'
    _description = 'TNA Period (Annual/Semester)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, name desc'

    name = fields.Char(
        string='Nama Periode TNA',
        required=True,
        copy=False,
        tracking=True,
        compute='_compute_name',
        store=True,
        readonly=False
    )
    year = fields.Integer(
        string='Tahun',
        required=True,
        tracking=True,
        default=lambda self: fields.Date.today().year
    )
    semester = fields.Selection([
        ('1', 'Semester I'),
        ('2', 'Semester II'),
        ('all', 'Setahun Penuh')
    ],
        string='Cakupan Semester',
        default='all',
        tracking=True
    )
    date_start_submission = fields.Date(
        string='Tanggal Mulai Pengisian',
        tracking=True
    )
    date_end_submission = fields.Date(
        string='Batas Akhir Pengisian',
        tracking=True
    )
    responsible_user_id = fields.Many2one(
        'res.users',
        string='Penanggung Jawab (SDM)',
        tracking=True,
        default=lambda self: self.env.user
    )
    submission_ids = fields.One2many(
        'tna.submission',
        'period_id',
        string='Form Usulan TNA Diterima'
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Dibuka untuk Pengisian'),
        ('closed', 'Pengisian Ditutup'),
        ('processing', 'Review & Approval SDM'),
        ('completed', 'Selesai')
    ],
        string='Status Periode',
        default='draft',
        copy=False,
        tracking=True,
        group_expand='_read_group_status_ids'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Perusahaan',
        default=lambda self: self.env.company,
        readonly=True
    )
    notes = fields.Text(string='Catatan Internal')

    _sql_constraints = [
        ('year_semester_company_uniq', 'unique (year, semester, company_id)',
         'Periode TNA untuk tahun dan semester yang sama sudah ada!')
    ]

    @api.depends('year', 'semester')
    def _compute_name(self):
        for period in self:
            if period.year:
                name = f"TNA {period.year}"
                if period.semester and period.semester != 'all':
                    semester_display = dict(self._fields['semester'].selection).get(period.semester)
                    name += f" - {semester_display}"
                period.name = name
            else:
                period.name = "Periode TNA Baru"

    @api.model
    def _read_group_status_ids(self, states, domain, order):
        """Untuk menampilkan semua status di Kanban view, bahkan yg kosong."""
        status_list = [key for key, val in self._fields['state'].selection]
        return status_list

    # --- Tombol Aksi Workflow ---
    def action_open_submission(self):
        for rec in self:
            if not rec.date_start_submission or not rec.date_end_submission:
                raise UserError("Tanggal Mulai dan Batas Akhir Pengisian harus diisi sebelum membuka periode.")
            if rec.date_start_submission > rec.date_end_submission:
                raise UserError("Tanggal Mulai Pengisian tidak boleh melebihi Batas Akhir Pengisian.")
            rec.state = 'open'

    def action_close_submission(self):
        self.write({'state': 'closed'})

    def action_start_processing(self):
        self.write({'state': 'processing'})

    def action_mark_completed(self):
        self.write({'state': 'completed'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})