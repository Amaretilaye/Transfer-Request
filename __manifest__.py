{
    'name': 'Product Transfer Request',
    'version': '16.0',
    'depends': ['base', 'stock','inventory_pb'],
    'author': 'Amare Tilaye',
    'category': 'Inventory',
    'description': """
    Module to handle transfer requests when one stock ask transfer request user can ask by this module user access and other rule done based one sorce location and destination location .
    """,
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/transfer_request_views.xml',
        'data/sequence_data.xml',
    ],
    'installable': True,
    'application': False,
}
