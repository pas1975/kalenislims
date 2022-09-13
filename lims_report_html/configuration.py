# This file is part of lims_report_html module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from trytond.model import fields
from trytond.pool import PoolMeta
from trytond.pyson import Eval


class Configuration(metaclass=PoolMeta):
    __name__ = 'lims.configuration'

    result_template = fields.Many2One('lims.report.template',
        'Default Report Template', domain=[
            ('report_name', '=', 'lims.result_report'),
            ('type', 'in', [None, 'base']),
            ['OR', ('active', '=', True),
                ('id', '=', Eval('result_template'))],
            ])
