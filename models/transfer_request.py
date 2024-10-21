from datetime import date

from odoo import models, fields, api, _
import logging
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class TransferRequest(models.Model):
    _name = 'stock.transfer.request'
    _description = 'Stock Transfer Request'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Request Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    sn = fields.Char(string='Request Reference')
    requester_id = fields.Many2one('res.users', string='Requester', default=lambda self: self.env.user)
    contact = fields.Many2one('res.partner', string='Contact')
    receiver_id = fields.Many2one('res.users', string='Receiver', default=lambda self: self.env.user)
    location_id = fields.Many2one('stock.location', string='From', required=True)
    location_dest_id = fields.Many2one('stock.location', string='To', required=True, readonly=True, default=lambda self: self._default_location_dest_id())
    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('done', 'Done'),
        ('rejected', 'Rejected')
    ], string='Status', readonly=True, default='draft')
    picking_id = fields.Many2one('stock.picking', string='Transfer', readonly=True)
    line_ids = fields.One2many('stock.transfer.request.line', 'request_id', required=True, string='Transfer Request Lines')
    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To', required=True)
    expire_date = fields.Char(string='Expire After Days', compute='_compute_expire_date')
    date_up_to_today = fields.Char(string='Date Number', compute='_compute_date_up_to_today')

    transfer_message = fields.Char(string='Transfer Status', compute='_compute_transfer_message', store=True)

    @api.depends('picking_id')
    def _compute_transfer_message(self):
        for record in self:
            if record.picking_id:
                record.transfer_message = record.picking_id.name
            else:
                record.transfer_message = 'No Transfer Created'


    @api.model
    def create(self, vals):
        if not vals.get('line_ids'):
            raise ValidationError(_('You must add at least one transfer request line.'))
        return super(TransferRequest, self).create(vals)

    def write(self, vals):
        res = super(TransferRequest, self).write(vals)
        for record in self:
            if not record.line_ids:
                raise ValidationError(_('You must add at least one transfer request line.'))
        return res

    @api.constrains('line_ids')
    def _check_lines(self):
        for record in self:
            if not record.line_ids:
                raise ValidationError(_('You must add at least one transfer request line.'))

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('stock.transfer.request') or 'New'
        return super(TransferRequest, self).create(vals)


    @api.depends('date_from', 'date_to')
    def _compute_expire_date(self):
        for record in self:
            if record.date_from and record.date_to:
                date_from = fields.Date.from_string(record.date_from)
                date_to = fields.Date.from_string(record.date_to)
                delta = (date_to - date_from).days + 1
                record.expire_date = str(delta)  # Store the number of days as a string
            else:
                record.expire_date = '0'

    @api.depends('date_from')
    def _compute_date_up_to_today(self):
        for record in self:
            if record.date_from:
                date_from = fields.Date.from_string(record.date_from)
                today = date.today()
                delta = (today - date_from).days + 1
                record.date_up_to_today = str(delta)
            else:
                record.date_up_to_today = '0'

    @api.depends('state', 'date_up_to_today', 'expire_date')
    def action_reject(self):
        for record in self:
            if record.date_up_to_today and record.expire_date:
                date_up_to_today = int(record.date_up_to_today)
                expire_date = int(record.expire_date)
                if date_up_to_today > expire_date:
                    record.state = 'rejected'

            else:

                record.state = 'rejected'
    #
    # def action_reject(self):
    #     self.state = 'rejected'

    def write(self, vals):
        res = super(TransferRequest, self).write(vals)
        for record in self:
            if record.state == 'requested':  # Check only when the state is 'requested'
                if record.date_up_to_today and record.expire_date:
                    date_up_to_today = int(record.date_up_to_today)
                    expire_date = int(record.expire_date)
                    if date_up_to_today > expire_date:
                        record.state = 'rejected'
        return res

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('stock.transfer.request') or _('New')
        return super(TransferRequest, self).create(vals)

    def _default_location_dest_id(self):
        user = self.env.user
        allowed_warehouses = user.allowed_warehouses_ids
        if allowed_warehouses:
            return allowed_warehouses[0].lot_stock_id.id
        return None

    @api.constrains('location_id', 'location_dest_id')
    def _check_location_types(self):
        for record in self:
            if record.location_id.usage == 'view' or record.location_dest_id.usage == 'view':
                raise UserError(_('You cannot take products from or deliver products to a location of type "view".'))

    def action_request(self):
        self.state = 'requested'


    def action_approve(self):
        self.ensure_one()
        user = self.env.user
        warehouse_id = self.location_id.warehouse_id.id

        # Check if the user has access to the warehouse
        if warehouse_id not in user.allowed_warehouses_ids.ids:
            _logger.error(f"User {user.name} does not have access to the warehouse: {warehouse_id}")
            raise UserError(_('You do not have access to the warehouse associated with the receiver address.'))

        # Proceed with approval if access is validated
        self.state = 'approved'

    def action_done(self):
        self.ensure_one()

        if not self.picking_id:
            # Determine the warehouse based on location_id
            warehouse_id = self.location_id.warehouse_id.id
            if not warehouse_id:
                _logger.error(f"No warehouse found for location_id: {self.location_id.id}")
                raise UserError(_('No warehouse associated with the receiver address'))

            # Find the appropriate picking type based on warehouse_id
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),  # Internal transfers
                ('warehouse_id', '=', warehouse_id)
            ], limit=1)

            if not picking_type:
                _logger.error(f"No picking type found for warehouse: {warehouse_id}")
                raise UserError(_('No appropriate picking type found for the warehouse'))

            # Create the picking record with specified locations
            picking = self.env['stock.picking'].create({
                'location_id': self.location_id.id,  # Source location
                'location_dest_id': self.location_dest_id.id,  # Destination location
                'picking_type_id': picking_type.id,  # Correct picking type
                'origin': self.name,
                'move_ids_without_package': [(0, 0, {
                    'name': line.product_id.name,
                    'product_id': line.product_id.id,
                    'reserved_availability': line.quantity,
                    'product_uom': line.product_id.uom_id.id,
                    'description_picking': line.description_piking,
                    'location_id': self.location_id.id,
                    'location_dest_id': self.location_dest_id.id,
                    'quantity_done': line.qty_done,
                }) for line in self.line_ids],
            })

            picking.action_confirm()
            self.picking_id = picking.id  # Set the reference

        # Update the state to 'done'
        self.state = 'done'


def action_reject(self):
    for record in self:
        record.state = 'rejected'


class TransferRequestLine(models.Model):
    _name = 'stock.transfer.request.line'
    _description = 'Stock Transfer Request Line'

    request_id = fields.Many2one('stock.transfer.request', string='Transfer Request', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Quantity', required=True)
    reserved_uom_qty = fields.Float(string='Reserved')
    qty_done = fields.Float(string='Done')
    # description_piking = fields.Char(string='Description', readonly=True, store=True)

    description_piking = fields.Char(string='Description Picking', compute='_compute_description_piking', store=True)

    @api.depends('product_id')
    def _compute_description_piking(self):
        for line in self:
            if line.product_id:
                line.description_piking = line.product_id.default_code


    parent_request_state = fields.Selection(
        related='request_id.state',
        string='Parent Request State',
        store=True,
        redonly=True,

    )


    @api.constrains('product_id', 'quantity', 'qty_done', 'parent_request_state')
    def _check_product_quantity(self):
        for line in self:
            if not line.product_id:
                raise ValidationError(_('You need to add at least one product.'))
            if line.quantity <= 0:
                raise ValidationError(_('You need to add at least one quantity.'))
            if line.parent_request_state == 'done' and line.qty_done <= 0:
                raise ValidationError(_('You need to set done quantity.'))



class PickingType(models.Model):
    _inherit = 'stock.picking.type'

    transfer_request_count = fields.Integer(
        string='Transfer Request Count',
        compute='_compute_transfer_request_count',
        store=True
    )

    @api.depends('code')
    def _compute_transfer_request_count(self):
        for picking_type in self:
            picking_type.transfer_request_count = self.env['stock.transfer.request'].search_count([
                ('state', 'in', ['requested', 'approved'])
])