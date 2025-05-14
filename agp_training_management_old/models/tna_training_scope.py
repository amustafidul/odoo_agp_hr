from odoo import models, fields


class TnaTrainingScope(models.Model):
    _name = 'tna.training.scope'
    _description = 'Training Scope Master Data'
    _order = 'name'

    name = fields.Char(string='Nama Lingkup Diklat', required=True, copy=False)
    description = fields.Text(string='Deskripsi')

    _sql_constraints = [
        ('name_uniq', 'unique (name)', "Nama Lingkup Diklat harus unik!")
    ]