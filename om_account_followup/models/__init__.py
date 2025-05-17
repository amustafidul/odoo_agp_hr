# -*- coding: utf-8 -*-

from . import account_move
from . import followup
from . import followup_partner
from . import partner
from . import settings

from odoo import fields, models
class ResPartner(models.Model):
	_inherit = 'res.partner'
	x_vendor_code = fields.Char(string="Code")
