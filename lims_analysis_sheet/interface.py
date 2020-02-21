# This file is part of lims_analysis_sheet module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from trytond.model import Workflow, ModelView, ModelSQL, fields, Unique
from trytond.wizard import Wizard, StateAction
from trytond.pool import Pool, PoolMeta
from trytond.pyson import PYSONEncoder, Eval, Bool, Or
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext

__all__ = ['TemplateAnalysisSheet', 'TemplateAnalysisSheetAnalysis',
    'AnalysisSheet', 'OpenAnalysisSheetData', 'Compilation']


class TemplateAnalysisSheet(ModelSQL, ModelView):
    'Analysis Sheet Template'
    __name__ = 'lims.template.analysis_sheet'

    interface = fields.Many2One('lims.interface', 'Device Interface',
        required=True, domain=[
            ('kind', '=', 'template'),
            ('state', '=', 'active')],
        states={'readonly': Bool(Eval('interface'))})
    name = fields.Char('Name', required=True)
    analysis = fields.One2Many('lims.template.analysis_sheet.analysis',
        'template', 'Analysis', required=True)
    max_qty_samples = fields.Integer('Maximum quantity of samples',
        help='For generation from racks')
    comments = fields.Text('Comments')
    pending_fractions = fields.Function(fields.Integer('Pending fractions'),
        'get_pending_fractions')

    @fields.depends('interface')
    def on_change_with_name(self, name=None):
        if self.interface:
            return self.interface.name

    @classmethod
    def get_pending_fractions(cls, records, name):
        context = Transaction().context
        cursor = Transaction().connection.cursor()
        pool = Pool()
        PlanificationServiceDetail = pool.get(
            'lims.planification.service_detail')
        PlanificationDetail = pool.get('lims.planification.detail')
        Planification = pool.get('lims.planification')
        NotebookLine = pool.get('lims.notebook.line')
        Notebook = pool.get('lims.notebook')
        Fraction = pool.get('lims.fraction')
        EntryDetailAnalysis = pool.get('lims.entry.detail.analysis')
        Analysis = pool.get('lims.analysis')
        TemplateAnalysis = pool.get('lims.template.analysis_sheet.analysis')

        res = dict((r.id, None) for r in records)

        date_from = context.get('date_from') or None
        date_to = context.get('date_to') or None
        if not (date_from and date_to):
            return res

        cursor.execute('SELECT nl.id '
            'FROM "' + NotebookLine._table + '" nl '
                'INNER JOIN "' + PlanificationServiceDetail._table +
                '" psd ON psd.notebook_line = nl.id '
                'INNER JOIN "' + PlanificationDetail._table + '" pd '
                'ON psd.detail = pd.id '
                'INNER JOIN "' + Planification._table + '" p '
                'ON pd.planification = p.id '
            'WHERE p.state = \'preplanned\'')
        preplanned_lines = [x[0] for x in cursor.fetchall()]
        preplanned_lines_ids = ', '.join(str(x)
            for x in [0] + preplanned_lines)

        sql_select = 'SELECT nl.analysis, nl.method, frc.id '
        sql_from = (
            'FROM "' + NotebookLine._table + '" nl '
            'INNER JOIN "' + Analysis._table + '" nla '
            'ON nla.id = nl.analysis '
            'INNER JOIN "' + Notebook._table + '" nb '
            'ON nb.id = nl.notebook '
            'INNER JOIN "' + Fraction._table + '" frc '
            'ON frc.id = nb.fraction '
            'INNER JOIN "' + EntryDetailAnalysis._table + '" ad '
            'ON ad.id = nl.analysis_detail ')
        sql_where = (
            'WHERE ad.plannable = TRUE '
            'AND nl.start_date IS NULL '
            'AND nl.annulled = FALSE '
            'AND nl.id NOT IN (' + preplanned_lines_ids + ') '
            'AND nla.behavior != \'internal_relation\' '
            'AND ad.confirmation_date::date >= %s::date '
            'AND ad.confirmation_date::date <= %s::date')

        with Transaction().set_user(0):
            cursor.execute(sql_select + sql_from + sql_where,
                (date_from, date_to,))
        notebook_lines = cursor.fetchall()
        if not notebook_lines:
            return res

        templates = {}
        for nl in notebook_lines:
            cursor.execute('SELECT template '
                'FROM "' + TemplateAnalysis._table + '" '
                'WHERE analysis = %s '
                'AND (method = %s OR method IS NULL)',
                (nl[0], nl[1]))
            template = cursor.fetchone()
            if not template:
                continue
            if template[0] not in templates:
                templates[template[0]] = set()
            templates[template[0]].add(nl[2])

        for t_id, fractions in templates.items():
            res[t_id] = len(fractions)
        return res


class TemplateAnalysisSheetAnalysis(ModelSQL, ModelView):
    'Template Analysis'
    __name__ = 'lims.template.analysis_sheet.analysis'

    template = fields.Many2One('lims.template.analysis_sheet', 'Template',
        required=True, ondelete='CASCADE', select=True)
    analysis = fields.Many2One('lims.analysis', 'Analysis',
        required=True, select=True)
    method = fields.Many2One('lims.lab.method', 'Method')

    @classmethod
    def validate(cls, template_analysis):
        super(TemplateAnalysisSheetAnalysis, cls).validate(template_analysis)
        for ta in template_analysis:
            ta.check_duplicated()

    def check_duplicated(self):
        clause = [
            ('id', '!=', self.id),
            ('analysis', '=', self.analysis.id),
            ]
        if self.method:
            clause.append(('method', '=', self.method.id))
        duplicated = self.search(clause)
        if duplicated:
            raise UserError(gettext(
                'lims_analysis_sheet.msg_template_analysis_unique',
                analysis=self.analysis.rec_name))


class AnalysisSheet(Workflow, ModelSQL, ModelView):
    'Analysis Sheet'
    __name__ = 'lims.analysis_sheet'

    template = fields.Many2One('lims.template.analysis_sheet', 'Template',
        required=True, readonly=True)
    compilation = fields.Many2One('lims.interface.compilation', 'Compilation',
        required=True, readonly=True)
    laboratory = fields.Many2One('lims.laboratory', 'Laboratory',
        readonly=True)
    professional = fields.Many2One('lims.laboratory.professional',
        'Professional', required=True, readonly=True)
    urgent = fields.Function(fields.Boolean('Urgent'), 'get_urgent')
    samples_qty = fields.Function(fields.Integer('Samples Qty.'),
        'get_samples_qty')
    number = fields.Char('Number', readonly=True)
    date = fields.Function(fields.DateTime('Date'), 'get_date')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ], 'State', required=True, readonly=True)
    planification = fields.Many2One('lims.planification', 'Planification',
        readonly=True)
    incomplete_sample = fields.Function(fields.Boolean('Incomplete sample'),
        'get_incomplete_sample')

    @classmethod
    def __setup__(cls):
        super(AnalysisSheet, cls).__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('compilation_uniq', Unique(t, t.compilation),
                'lims_analysis_sheet.msg_sheet_compilation_unique'),
            ]
        cls._transitions |= set((
            ('draft', 'active'),
            ))
        cls._buttons.update({
            'view_data': {
                'invisible': Eval('state') == 'draft',
                },
            'activate': {
                'invisible': Eval('state') != 'draft',
                },
            })

    @staticmethod
    def default_state():
        return 'draft'

    def get_date(self, name):
        return self.compilation.date_time

    @classmethod
    def get_urgent(cls, sheets, name):
        pool = Pool()
        Data = pool.get('lims.interface.data')
        NotebookLine = pool.get('lims.notebook.line')

        result = {}
        for s in sheets:
            result[s.id] = False
            nl_field = (s.template.interface.notebook_line_field and
                s.template.interface.notebook_line_field.alias or None)
            if not nl_field:
                continue
            with Transaction().set_context(
                    lims_interface_table=s.compilation.table.id):
                lines = Data.search([('compilation', '=', s.compilation.id)])
                for line in lines:
                    nl = getattr(line, nl_field)
                    if nl and NotebookLine(nl).service.urgent:
                        result[s.id] = True
                        break
        return result

    @classmethod
    def get_samples_qty(cls, sheets, name):
        pool = Pool()
        Data = pool.get('lims.interface.data')
        NotebookLine = pool.get('lims.notebook.line')

        result = {}
        for s in sheets:
            result[s.id] = 0
            nl_field = (s.template.interface.notebook_line_field and
                s.template.interface.notebook_line_field.alias or None)
            if not nl_field:
                continue
            with Transaction().set_context(
                    lims_interface_table=s.compilation.table.id):
                samples = []
                lines = Data.search([('compilation', '=', s.compilation.id)])
                for line in lines:
                    nl = getattr(line, nl_field)
                    if nl:
                        samples.append(NotebookLine(nl).fraction.id)
                result[s.id] = len(list(set(samples)))
        return result

    @classmethod
    def get_incomplete_sample(cls, sheets, name):
        pool = Pool()
        Data = pool.get('lims.interface.data')
        NotebookLine = pool.get('lims.notebook.line')

        result = {}
        for s in sheets:
            result[s.id] = False
            nl_field = (s.template.interface.notebook_line_field and
                s.template.interface.notebook_line_field.alias or None)
            if not nl_field:
                continue
            with Transaction().set_context(
                    lims_interface_table=s.compilation.table.id):
                samples = {}
                lines = Data.search([('compilation', '=', s.compilation.id)])
                for line in lines:
                    nl = getattr(line, nl_field)
                    if not nl:
                        continue
                    nl = NotebookLine(nl)
                    if nl.fraction.id not in samples:
                        samples[nl.fraction.id] = []
                    samples[nl.fraction.id].append(nl.analysis.id)

                template_analysis = [ta.analysis.id
                    for ta in s.template.analysis]
                result[s.id] = False
                for k, v in samples.items():
                    if not all(x in v for x in template_analysis):
                        result[s.id] = True
                        break
        return result

    @classmethod
    def create(cls, vlist):
        vlist = cls.set_number(vlist)
        sheets = super(AnalysisSheet, cls).create(vlist)
        cls.update_compilation(sheets)
        return sheets

    @classmethod
    def set_number(cls, vlist):
        pool = Pool()
        Config = pool.get('lims.configuration')
        Sequence = pool.get('ir.sequence')

        config = Config(1)
        if not config.analysis_sheet_sequence:
            return vlist

        vlist = [x.copy() for x in vlist]
        for values in vlist:
            number = Sequence.get_id(config.analysis_sheet_sequence.id)
            values['number'] = number
        return vlist

    @classmethod
    def update_compilation(cls, sheets):
        Compilation = Pool().get('lims.interface.compilation')
        to_save = []
        for s in sheets:
            compilation = Compilation(s.compilation.id)
            compilation.analysis_sheet = s.id
            to_save.append(compilation)
        Compilation.save(to_save)

    @classmethod
    def delete(cls, sheets):
        Compilation = Pool().get('lims.interface.compilation')
        compilations = [s.compilation for s in sheets]
        super(AnalysisSheet, cls).delete(sheets)
        Compilation.delete(compilations)

    @classmethod
    @ModelView.button
    @Workflow.transition('active')
    def activate(cls, sheets):
        Compilation = Pool().get('lims.interface.compilation')
        Compilation.activate([s.compilation for s in sheets])

    @classmethod
    @ModelView.button_action(
        'lims_analysis_sheet.wiz_open_analysis_sheet_data')
    def view_data(cls, sheets):
        pass

    def get_new_compilation(self):
        Compilation = Pool().get('lims.interface.compilation')
        compilation = Compilation(
            interface=self.template.interface.id,
            revision=self.template.interface.revision,
            )
        return compilation

    def create_lines(self, lines):
        Data = Pool().get('lims.interface.data')

        interface = self.template.interface
        if not interface.notebook_line_field:
            return

        with Transaction().set_context(
                lims_interface_table=self.compilation.table.id):
            data = []
            for nl in lines:
                line = {'compilation': self.compilation.id}
                line[interface.notebook_line_field.alias] = nl.id
                if interface.analysis_field:
                    if interface.analysis_field.type_ == 'many2one':
                        line[interface.analysis_field.alias] = nl.analysis.id
                    else:
                        line[interface.analysis_field.alias] = (
                            nl.analysis.rec_name)
                if interface.fraction_field:
                    if interface.fraction_field.type_ == 'many2one':
                        line[interface.fraction_field.alias] = nl.fraction.id
                    else:
                        line[interface.fraction_field.alias] = (
                            nl.fraction.rec_name)
                if interface.repetition_field:
                    line[interface.repetition_field.alias] = nl.repetition
                data.append(line)

            if data:
                Data.create(data)


class OpenAnalysisSheetData(Wizard):
    'Open Analysis Sheet Data'
    __name__ = 'lims.analysis_sheet.open_data'

    start = StateAction('lims_interface.act_open_compilation_data')

    def do_start(self, action):
        AnalysisSheet = Pool().get('lims.analysis_sheet')

        context = {
            'lims_interface_compilation': None,
            'lims_interface_table': None,
            }
        domain = [('compilation', '=', None)]
        name = ''

        sheet_id = Transaction().context.get('active_id', None)
        if sheet_id:
            sheet = AnalysisSheet(sheet_id)
            context['lims_interface_compilation'] = sheet.compilation.id
            context['lims_interface_table'] = sheet.compilation.table.id
            domain = [('compilation', '=', sheet.compilation.id)]
            name = ' (%s - %s)' % (sheet.number, sheet.template.name)
        action['pyson_context'] = PYSONEncoder().encode(context)
        action['pyson_domain'] = PYSONEncoder().encode(domain)
        action['name'] += name
        return action, {}


class Compilation(metaclass=PoolMeta):
    __name__ = 'lims.interface.compilation'

    analysis_sheet = fields.Many2One('lims.analysis_sheet', 'Analysis Sheet')

    @classmethod
    def __setup__(cls):
        super(Compilation, cls).__setup__()
        cls.date_time.states['readonly'] = Bool(Eval('analysis_sheet'))
        if 'analysis_sheet' not in cls.date_time.depends:
            cls.date_time.depends.append('analysis_sheet')
        cls.interface.states['readonly'] = Bool(Eval('analysis_sheet'))
        if 'analysis_sheet' not in cls.interface.depends:
            cls.interface.depends.append('analysis_sheet')
        cls.table_name.states['readonly'] = Bool(Eval('analysis_sheet'))
        if 'analysis_sheet' not in cls.table_name.depends:
            cls.table_name.depends.append('analysis_sheet')
        cls.revision.states['readonly'] = Or(Bool(Eval('analysis_sheet')),
            Eval('state') != 'draft')
        if 'analysis_sheet' not in cls.revision.depends:
            cls.revision.depends.append('analysis_sheet')

        cls._buttons['draft']['invisible'] = Or(Eval('state') != 'active',
            Bool(Eval('analysis_sheet')))
        cls._buttons['activate']['invisible'] = Or(Eval('state') != 'draft',
            Bool(Eval('analysis_sheet')))
        cls._buttons['validate_']['invisible'] = Or(Eval('state') != 'active',
            Bool(Eval('analysis_sheet')))
        cls._buttons['confirm']['invisible'] = Or(Eval('state') != 'validated',
            Bool(Eval('analysis_sheet')))
        #cls._buttons['view_data']['invisible'] = Or(Eval('state') == 'draft',
            #Bool(Eval('analysis_sheet')))
        #cls._buttons['collect']['invisible'] = Or(Eval('state') != 'active',
            #Bool(Eval('analysis_sheet')))