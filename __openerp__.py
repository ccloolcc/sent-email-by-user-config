# -*- encoding: utf-8 -*-

{
    'name': 'send mail from user config',
    'version': '1.0',
    "category" : "Generic Modules/Report",
    'description': """set your email and password in preferences, and your smtp host in system setup.
     """,
    'author': 'FRANK',
    'depends': ['base'],
    'init_xml': [ ],
    'update_xml': ['res_user.xml'],
    'installable': True,
    'auto_install': False
}