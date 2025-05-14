from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
import tempfile
import pandas as pd

class WizardImportEmployee(models.TransientModel):
    _name = 'wizard.import.employee'
    _description = 'Wizard Import Data Pegawai + Histori Jabatan'

    file = fields.Binary(string="Upload File Excel", required=True)
    filename = fields.Char(string="File Name")

    def action_import(self):
        if not self.file:
            raise UserError(_("Silakan upload file terlebih dahulu."))

        # Decode & simpan file ke sementara
        file_content = base64.b64decode(self.file)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_file.write(file_content)
            tmp_file_path = tmp_file.name

        try:
            df = pd.read_excel(tmp_file_path)
        except Exception as e:
            raise UserError(_("Gagal membaca file Excel: %s" % str(e)))

        required_columns = ['name', 'histori_jabatan_ids/employment_type', 'histori_jabatan_ids/grade_id']
        missing_cols = [col for col in required_columns if col not in df.columns]
        if missing_cols:
            raise UserError(_("Kolom wajib berikut tidak ditemukan di file Excel: %s" % ", ".join(missing_cols)))

        for index, row in df.iterrows():
            try:
                name = str(row.get('name', '')).strip().upper()
                if not name:
                    continue  # skip kosong

                employment_type = str(row.get('histori_jabatan_ids/employment_type', '')).strip().lower()
                nip_organik = str(row.get('nip_organik', '')).strip()
                nip_pkwt = str(row.get('nip_pkwt', '')).strip()
                work_email = str(row.get('work_email', '')).strip()
                mobile_phone = str(row.get('mobile_phone', '')).strip()
                grade_name = str(row.get('histori_jabatan_ids/grade_id', '')).strip()
                tmt_date = row.get('histori_jabatan_ids/tmt_date')
                tanggal_pengangkatan = row.get('histori_jabatan_ids/tanggal_pengangkatan')
                tanggal_selesai_kontrak = row.get('histori_jabatan_ids/tanggal_selesai_kontrak')

                jabatan_name = str(row.get('histori_jabatan_ids/keterangan_jabatan_id', '')).strip()
                fungsi_name = str(row.get('histori_jabatan_ids/fungsi_penugasan_id', '')).strip()
                branch_name = str(row.get('histori_jabatan_ids/hr_branch_id', '')).strip()

                grade = self.env['odoo.payroll.grade'].search([('name', '=', grade_name)], limit=1)
                if not grade:
                    raise UserError(_("Grade tidak ditemukan: %s" % grade_name))

                jabatan = self.env['hr.employee.keterangan.jabatan'].search([('name', 'ilike', jabatan_name)], limit=1)
                fungsi = self.env['hr.employee.fungsi.penugasan'].search([('name', 'ilike', fungsi_name)], limit=1)
                branch = self.env['hr.branch'].search([('name', 'ilike', branch_name)], limit=1)

                employee = self.env['hr.employee'].search([('name', '=', name)], limit=1)
                if not employee:
                    employee = self.env['hr.employee'].create({
                        'name': name,
                        'employment_type': employment_type,
                        'nip_organik': nip_organik,
                        'nip_pkwt': nip_pkwt,
                        'work_email': work_email,
                        'mobile_phone': mobile_phone,
                        'grade_id': grade.id,
                    })

                self.env['hr.employee.histori.jabatan'].create({
                    'employee_id': employee.id,
                    'employment_type': employment_type,
                    'keterangan_jabatan_id': jabatan.id or False,
                    'fungsi_penugasan_id': fungsi.id or False,
                    'hr_branch_id': branch.id or False,
                    'grade_id': grade.id,
                    'tmt_date': tmt_date,
                    'tanggal_pengangkatan': tanggal_pengangkatan,
                    'tanggal_selesai_kontrak': tanggal_selesai_kontrak,
                })

            except Exception as e:
                raise UserError(_("Gagal memproses baris ke-%s: %s" % (index + 2, str(e))))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Sukses'),
                'message': _('Data berhasil diimport.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }