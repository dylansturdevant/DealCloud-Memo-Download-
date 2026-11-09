"""Bounded .xlsx reading, column mapping and row validation (no network)."""
from __future__ import annotations
import datetime as dt
import io
import re
import zipfile

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_ROWS = 3000
MAX_COLUMNS = 100
POLICIES = ['Priority fallback', 'Latest available', 'Final', 'Screening', 'Follow-On', 'Update']
POPULATIONS = ['Primaries', 'CoInvestments', 'Secondaries']


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


def workbook_bytes(data):
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError('Use a nonempty .xlsx file no larger than 10 MiB.')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise ValueError('Expanded workbook exceeds 80 MiB. Upload a small deal-list workbook.')
            if any(info.flag_bits & 1 for info in archive.infolist()):
                raise ValueError('Password-protected Excel files are not supported.')
    except zipfile.BadZipFile:
        raise ValueError('Use a valid, unencrypted .xlsx workbook; .xls/.xlsm are not supported.') from None
    from openpyxl import load_workbook
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception:
        raise ValueError('Could not read this workbook. Save a small unencrypted .xlsx with values only.') from None


def sheet_names(data):
    workbook = workbook_bytes(data)
    try:
        return workbook.sheetnames
    finally:
        workbook.close()


def read_sheet(data, sheet, header_row=1):
    if not 1 <= header_row <= 50:
        raise ValueError('Header row must be between 1 and 50.')
    workbook = workbook_bytes(data)
    try:
        if sheet not in workbook.sheetnames:
            raise ValueError('Choose a sheet in the uploaded workbook.')
        ws = workbook[sheet]
        if (ws.max_column or 0) > MAX_COLUMNS or (ws.max_row or 0) > MAX_ROWS + header_row:
            raise ValueError('Use a dedicated list sheet with at most 3,000 data rows and 100 columns, with no formatting far below the table.')
        records = list(ws.iter_rows(min_row=header_row, max_row=MAX_ROWS + header_row + 1, max_col=min(ws.max_column or 1, MAX_COLUMNS)))
        if not records:
            raise ValueError('The selected sheet is empty.')
        headers=[]; seen=set()
        for index, cell in enumerate(records[0], 1):
            label = str(cell.value).strip() if cell.value is not None else f'Column {index}'
            if cell.data_type == 'f':
                raise ValueError('Header cells must be values, not formulas.')
            if label in seen:
                raise ValueError('Column headers must be unique. Rename duplicate headers in Excel.')
            seen.add(label);headers.append(label)
        rows=[]
        for row_number, cells in enumerate(records[1:], header_row + 1):
            if not any(c.value is not None and str(c.value).strip() for c in cells):
                continue
            if row_number > MAX_ROWS + header_row:
                raise ValueError('The selected sheet exceeds 3,000 data rows.')
            values={headers[i]: c.value for i,c in enumerate(cells)}
            formulas=[headers[i] for i,c in enumerate(cells) if c.data_type=='f']
            rows.append({'source_row':row_number, 'values':values, 'formula_columns':formulas})
        if not rows:
            raise ValueError('No data rows found below the selected header.')
        return headers, rows
    finally:
        workbook.close()


def suggested_mapping(headers):
    aliases={'deal_name':['dealname','deal','investmentname','fundname'],
             'population':['population','structure','dealtype'],
             'client':['clientname','client','clientfund','clientaccount','account','investor','lp','lpname','folder'],
             'quarters':['quarters','quarter','qtr','period'],
             'year':['year','years','fiscalyear','fy','calendaryear','reportingyear'],
             'memo_type':['memotype','memostage','requestedmemo']}
    return {field:next((h for h in headers if normalized(h) in names), None) for field,names in aliases.items()}


def parse_population(value):
    aliases={'primaries':'Primaries','primary':'Primaries','primarypartnership':'Primaries',
             'fund':'Primaries','coinvestments':'CoInvestments','coinvestment':'CoInvestments',
             'directtransaction':'CoInvestments','secondaries':'Secondaries','secondary':'Secondaries',
             'secondarytransaction':'Secondaries'}
    return aliases.get(normalized(value))


def parse_policy(value):
    if value is None or not str(value).strip():
        return 'Use app setting'
    aliases={normalized(p):p for p in POLICIES}
    aliases.update({'useappsetting':'Use app setting','default':'Use app setting',
                    'followon':'Follow-On','addendum':'Update','updateaddendum':'Update',
                    'latest':'Latest available','priority':'Priority fallback'})
    return aliases.get(normalized(value))


def _full_year(text):
    year=int(text)
    return 2000+year if len(text)==2 else year


def parse_year(value):
    """Optional Year cell -> 4-digit int or None. Accepts 2026, 2026.0, FY2026, FY26, '26 or a date."""
    if value is None or (isinstance(value,str) and not value.strip()):
        return None
    if isinstance(value,(dt.date,dt.datetime)):
        return value.year
    if isinstance(value,bool):
        raise ValueError('Year must be a year such as 2026 or FY2026.')
    if isinstance(value,(int,float)):
        if not float(value).is_integer():
            raise ValueError('Year must be a whole year such as 2026.')
        value=str(int(value))
    match=re.fullmatch(r"(?:FY|CY)?\s*'?((?:19|20)\d{2}|\d{2})",str(value).strip(),flags=re.I)
    if not match:
        raise ValueError('Year must be a year such as 2026, FY2026 or FY26.')
    year=_full_year(match[1])
    if not 1990<=year<=2099:
        raise ValueError('Year must be between 1990 and 2099.')
    return year


_YEAR=r"(?:FY|CY)?'?((?:19|20)\d{2}|\d{2})"
_QUARTER_FORMS=[
    re.compile(r"Q([1-4])(?:[\s\-/_.,']*"+_YEAR+r")?",re.I),          # Q3, Q3 2026, Q3-26, Q3'26, Q3 FY26
    re.compile(_YEAR+r"[\s\-/_.,]*Q([1-4])",re.I),                     # 2026 Q3, 2026-Q3, FY26 Q3
    re.compile(r"([1-4])Q(?:[\s\-/_.,']*"+_YEAR+r")?",re.I),          # 3Q, 3Q26, 3Q 2026
    re.compile(r"(?:quarter|qtr)\s*([1-4])(?:[\s\-/_.,']*"+_YEAR+r")?",re.I),  # Quarter 3 2026
]


def _one_period(part):
    """'Q3 2026' style text -> (quarter, year or None); a bare year -> (None, year)."""
    text=re.sub(r'\s+',' ',part.strip())
    if re.fullmatch(r'[1-4]',text):
        return int(text),None
    for number,form in enumerate(_QUARTER_FORMS):
        match=form.fullmatch(text)
        if match:
            quarter,year=(match[2],match[1]) if number==1 else (match[1],match[2])
            return int(quarter),(_full_year(year) if year else None)
    if re.fullmatch(r"(?:FY|CY)?\s*(?:19|20)\d{2}",text,flags=re.I):
        return None,parse_year(text)
    raise ValueError('Quarter must be Q1–Q4, optionally with a year (Q3 2026, 2026 Q3, Q3-26, 3Q26); '
                     'separate multiple quarters with semicolons.')


def parse_quarters(value,year=None):
    """Quarter cell (+ optional Year cell) -> ordered unique labels: 'Q3 2026', 'Q3' or '2026'.

    A Year cell supplies the year for quarters written without one, and on its
    own (blank quarter) gives a year-only folder. A conflicting year is an error.
    """
    if isinstance(value,(dt.date,dt.datetime)):
        raise ValueError('Quarter is a date cell. Type it as text such as Q3 2026, or use a Year column.')
    if isinstance(value,(int,float)) and not isinstance(value,bool) and float(value).is_integer():
        value=str(int(value))   # numeric cell: 3 -> Q3, 2026 -> year-only
    if value is None or not str(value).strip():
        return [str(year)] if year else []
    found=[]
    for part in re.split(r'[;,|\n]+',str(value)):
        if not part.strip():
            continue
        quarter,part_year=_one_period(part)
        if year and part_year and part_year!=year:
            raise ValueError(f'Quarter "{part.strip()}" has a different year than the Year column ({year}).')
        part_year=part_year or year
        label=(f'Q{quarter}' if quarter else '')+(f' {part_year}' if part_year else '')
        label=label.strip()
        if label not in found:
            found.append(label)
    return found


def validate_rows(records, mapping, default_population):
    if not mapping.get('deal_name'):
        raise ValueError('Map a Deal Name column.')
    if default_population not in POPULATIONS:
        raise ValueError('Choose a supported default population.')
    valid=[]; errors=[]
    for record in records:
        values=record['values']; source=record['source_row']; messages=[]
        def get(field):
            column=mapping.get(field)
            return values.get(column) if column else None
        mapped={c for c in mapping.values() if c}
        if mapped.intersection(record.get('formula_columns', [])):
            messages.append('Mapped columns contain formulas. Paste values into the list first.')
        deal=get('deal_name')
        if not isinstance(deal,str) or not deal.strip():
            messages.append('Deal Name must be nonempty text.')
        elif len(deal.strip())>300:
            messages.append('Deal Name exceeds 300 characters.')
        population_value=get('population')
        population=default_population if population_value is None or not str(population_value).strip() else parse_population(population_value)
        if not population:
            messages.append('Unsupported population/structure label; use Primaries, CoInvestments or Secondaries.')
        policy=parse_policy(get('memo_type'))
        if policy is None:
            messages.append('Unsupported Memo Type. Use Final, Screening, Follow-On, Update, Priority fallback or Latest available.')
        client=get('client')
        if isinstance(client,(int,float)) and not isinstance(client,bool):
            # Numeric client codes typed into Excel arrive as numbers; keep them as folder text.
            client=str(int(client)) if float(client).is_integer() else str(client)
        if client is not None and (not isinstance(client,str) or len(client.strip())>200):
            messages.append('Client must be text up to 200 characters or blank.')
        try:
            quarters=parse_quarters(get('quarters'),parse_year(get('year')))
        except ValueError as exc:
            quarters=[]; messages.append(str(exc))
        if messages:
            errors.append({'Source Row':source,'Deal Name':str(deal or ''),'Issue':' '.join(messages)})
        else:
            valid.append({'source_row':source,'deal_name':deal.strip(),'population':population,
                'client':str(client or '').strip(),'quarters':quarters,'memo_type':policy})
    return valid, errors


def template_bytes():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.worksheet.datavalidation import DataValidation
    workbook=Workbook();sheet=workbook.active;sheet.title='Deals'
    sheet.append(['Deal Name','Population','Client Name','Year','Quarter','Memo Type'])
    sheet.append(['REPLACE with exact DealCloud name','Primaries','','','',''])
    sheet.freeze_panes='A2';sheet.auto_filter.ref='A1:F2'
    for c in sheet[1]:
        c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='16324F')
    for col,width in [('A',65),('B',24),('C',36),('D',10),('E',22),('F',26)]:sheet.column_dimensions[col].width=width
    for col,formula in [('B','"Primaries,CoInvestments,Secondaries"'),('F','"Final,Screening,Follow-On,Update,Priority fallback,Latest available"')]:
        validation=DataValidation(type='list',formula1=formula,allow_blank=True);validation.errorTitle='Choose a supported value';validation.error='Use an item from the list or leave blank.';validation.showErrorMessage=True
        sheet.add_data_validation(validation);validation.add(f'{col}2:{col}3001')
    notes=workbook.create_sheet('Instructions')
    for row in [
        ['Field','Meaning'],['Deal Name','Required. Exact tenant deal/fund name. No fuzzy matching or workbook IDs treated as API IDs.'],
        ['Population','Optional. Primaries, CoInvestments or Secondaries. Blank uses the app default. Structure aliases Primary Partnership/Direct Transaction/Secondary Transaction are accepted.'],
        ['Client Name','Optional; used only by the "Folder per client" save option. Repeat a deal on one row per client that needs it: the memo downloads once and is copied into each client folder. Case/extra spaces are ignored when grouping. Local folder name only — not used for matching or entitlement. Ignored in "One folder" mode.'],
        ['Year','Optional; "Folder per client" only. e.g. 2026 or FY2026. Adds a year folder inside the client folder (Client/2026/). Fills in the year for quarters typed without one.'],
        ['Quarter','Optional; "Folder per client" only. Q1, Q2, Q3 or Q4, with or without a year (Q3 2026, 2026 Q3, Q3-26, 3Q26 or just 3 with a Year column). Separate several with semicolons, e.g. Q1; Q3. Saves to Client/2026/Q3/. In the app you can keep a copy in every quarter listed, or only the earliest or latest per year. Folder placement only, never a memo-date filter.'],
        ['Memo Type','Optional. A specific stage means that stage ONLY. Priority fallback tries Final then Screening then Follow-On then Update. Latest available uses newest IC date across all supported stages. Blank uses the app setting.'],
        ['Audience','Chosen in the app: Internal then Client, Internal only, or Client only.'],
        ['Output','Chosen in the app. One folder: each unique deal/memo saved once in the batch folder. Folder per client: one folder per Client Name (blank → "No Client"), each containing every memo requested for that client. IC date is only for selection, not folder placement.'],
        ['Format','One header row, values only (no formulas), one request per row. Upload .xlsx up to 10 MiB with at most 3,000 rows and 100 columns. Replace the sample row.'],
        ['Preview','Required before downloading; flags unmatched/ambiguous names and coverage gaps. Candidate availability is not guaranteed file access.'],
        ['Privacy','Deal/client list and results may be confidential. Internal memos in a client folder are not automatically approved for that client. Never enter credentials in this workbook.']]:notes.append(row)
    notes.column_dimensions['A'].width=24;notes.column_dimensions['B'].width=115
    for row in notes:
        for cell in row:cell.alignment=Alignment(wrap_text=True,vertical='top')
        notes.row_dimensions[row[0].row].height=42
    output=io.BytesIO();workbook.save(output);return output.getvalue()
