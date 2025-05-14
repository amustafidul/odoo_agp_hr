# agp_training_management/__manifest__.py
{
    'name': 'AGP Training Management',  # Sesuai permintaan lo
    'version': '16.0.1.0.0',  # Sesuaikan versi Odoo lo
    'category': 'Human Resources/Training',
    'summary': 'Comprehensive Training Need Analysis (TNA), Training Execution, and Evaluation.',
    'description': """
        This module integrates Training Need Analysis (TNA) with training execution
        and post-training evaluation, incorporating fuzzy logic for results.
        Features:
        - TNA Period Management
        - TNA Submission by Department/Branch
        - TNA Proposal and Approval by Central HR
        - Training Execution and Realization Tracking (replaces old Training Course flow)
        - Post-Training Evaluation with Fuzzy Logic Decision
        - Employee Training History
        - Reporting for TNA and Training Realization
    """,
    'author': 'Ibad - Safepedia Global Teknologi',
    'website': 'https://www.safepedia.co/',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'mail',
        'base_multi_branch',
        'agp_employee_ib',
        'hr_contract',
        'hr_contract_types',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/training_management_security_rules.xml',
        'data/ir_cron_data.xml',
        'data/ir_sequence_data.xml',
        # test
        'views/tna_training_scope_views.xml',
        'views/tna_period_views.xml',
        'views/tna_submission_views.xml',
        'views/tna_proposed_training_views.xml',

        # 'views/training_course_views.xml',
        # 'views/training_evaluation_views.xml',
        #
        # 'views/hr_employee_views.xml',
        #
        'views/training_management_menus.xml',

        # 'reports/tna_rekap_report_templates.xml', # Jika ada QWeb report
        # 'reports/training_reports.xml', # Action untuk report
    ],
    'assets': {
        'web.assets_backend': [
            'agp_training_management/static/src/css/custom_styles.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}