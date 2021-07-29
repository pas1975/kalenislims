# -*- coding: utf-8 -*-
# This file is part of lims_account_invoice module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext


class FractionType(metaclass=PoolMeta):
    __name__ = 'lims.fraction.type'

    invoiceable = fields.Boolean('Invoiceable')

    @staticmethod
    def default_invoiceable():
        return True


class Entry(metaclass=PoolMeta):
    __name__ = 'lims.entry'

    @classmethod
    def on_hold(cls, entries):
        super().on_hold(entries)
        cls.create_invoice_lines(entries)

    @classmethod
    def create_invoice_lines(cls, entries):
        Service = Pool().get('lims.service')

        with Transaction().set_context(_check_access=False):
            services = Service.search([
                ('entry', 'in', [e.id for e in entries]),
                ('annulled', '=', False),
                ])
        for service in services:
            service.create_invoice_line()


class Fraction(metaclass=PoolMeta):
    __name__ = 'lims.fraction'

    @classmethod
    def confirm(cls, fractions):
        fractions_to_invoice = [f for f in fractions if
            f.sample.entry.state != 'pending']
        super().confirm(fractions)
        if fractions_to_invoice:
            cls.create_invoice_lines(fractions_to_invoice)

    @classmethod
    def create_invoice_lines(cls, fractions):
        Service = Pool().get('lims.service')

        with Transaction().set_context(_check_access=False):
            services = Service.search([
                ('fraction', 'in', [f.id for f in fractions]),
                ('annulled', '=', False),
                ])
        for service in services:
            service.create_invoice_line()


class Service(metaclass=PoolMeta):
    __name__ = 'lims.service'

    @classmethod
    def create(cls, vlist):
        services = super().create(vlist)
        services_to_invoice = [s for s in services if
            s.entry.state == 'pending']
        for service in services_to_invoice:
            service.create_invoice_line()
        return services

    def create_invoice_line(self):
        InvoiceLine = Pool().get('account.invoice.line')

        if (not self.fraction.type.invoiceable or
                self.fraction.cie_fraction_type):
            return
        invoice_line = self.get_invoice_line()
        if not invoice_line:
            return
        with Transaction().set_context(_check_access=False):
            InvoiceLine.create([invoice_line])

    def get_invoice_line(self):
        Company = Pool().get('company.company')

        company = Transaction().context.get('company')
        currency = Company(company).currency.id
        product = self.analysis.product if self.analysis else None
        if not product:
            return
        account_revenue = product.account_revenue_used
        if not account_revenue:
            raise UserError(
                gettext('lims_account_invoice.msg_missing_account_revenue',
                    product=self.analysis.product.rec_name,
                    service=self.rec_name))

        party = self.entry.invoice_party
        taxes = []
        pattern = {}
        for tax in product.customer_taxes_used:
            if party.customer_tax_rule:
                tax_ids = party.customer_tax_rule.apply(tax, pattern)
                if tax_ids:
                    taxes.extend(tax_ids)
                continue
            taxes.append(tax.id)
        if party.customer_tax_rule:
            tax_ids = party.customer_tax_rule.apply(None, pattern)
            if tax_ids:
                taxes.extend(tax_ids)
        taxes_to_add = None
        if taxes:
            taxes_to_add = [('add', taxes)]

        return {
            'company': company,
            'currency': currency,
            'invoice_type': 'out',
            'party': party,
            'description': self.number + ' - ' + self.analysis.rec_name,
            'origin': str(self),
            'quantity': 1,
            'unit': product.default_uom,
            'product': product,
            'unit_price': Decimal('1.00'),
            'taxes': taxes_to_add,
            'account': account_revenue,
            }

    @classmethod
    def delete(cls, services):
        cls.delete_invoice_lines(services)
        super().delete(services)

    @classmethod
    def write(cls, *args):
        super().write(*args)
        actions = iter(args)
        for services, vals in zip(actions, actions):
            if vals.get('annulled'):
                cls.delete_invoice_lines(services)

    @classmethod
    def delete_invoice_lines(cls, services):
        InvoiceLine = Pool().get('account.invoice.line')

        lines_to_delete = []
        for service in services:
            with Transaction().set_context(_check_access=False):
                lines = InvoiceLine.search([
                    ('origin', '=', str(service)),
                    ])
            lines_to_delete.extend(lines)
        if lines_to_delete:
            for line in lines_to_delete:
                if line.invoice:
                    raise UserError(gettext(
                        'lims_account_invoice.msg_delete_service_invoice'))
            with Transaction().set_context(_check_access=False,
                    delete_service=True):
                InvoiceLine.delete(lines_to_delete)


class ManageServices(metaclass=PoolMeta):
    __name__ = 'lims.manage_services'

    def create_service(self, service, fraction):
        new_service = super().create_service(service, fraction)
        new_service.create_invoice_line()
        return new_service


class EditSampleService(metaclass=PoolMeta):
    __name__ = 'lims.sample.edit_service'

    def create_service(self, service, fraction):
        new_service = super().create_service(service, fraction)
        new_service.create_invoice_line()
        return new_service


class AddSampleService(metaclass=PoolMeta):
    __name__ = 'lims.sample.add_service'

    def create_service(self, service, fraction):
        new_service = super().create_service(service, fraction)
        new_service.create_invoice_line()
        return new_service
