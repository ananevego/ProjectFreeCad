"""Independent reader/validator for the supported CDS component record profile.

Checked against Schematic-Constructor e7443c3, Documents::ReadGraphics and
FreePcbView::FindStrInFile. This is neither a general CDS parser nor a GUI test.
All graphics numbers are native nanometres; header units only affect the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from .model import SymbolParseError

TARGET_REVISION = 'e7443c374f5c8644fb3483f794a50161de60dd01'
TARGET_VERSION = '1.429'
PROFILE = 'schemator-cds-straight-v1'
PART_OUTLINE, PART_NAME, PIN_LINE, PIN_NUMBER = 6, 7, 8, 9
FOOTPRINT, PART_VALUE, PIN_DESCRIPTION = 12, 13, 14
INT_MAX = 2**31 - 1
PIN_IDENTIFIER = re.compile(r'[A-Za-z_]*[1-9][0-9]*\Z')
REFERENCE = re.compile(r'[A-Za-z_]+[1-9][0-9]*\Z')


@dataclass
class TextRecord:
    value: str
    x: int
    y: int
    layer: int
    angle: int
    size: int
    width: int
    merge: int = -1
    submerge: int = -1
    font: int = 2  # SIMPLEX, smfontutil.h
    options: int = 1  # bit PDF_DEF, TextList.h


@dataclass
class Corner:
    x: int
    y: int
    style: int = 0
    node: int = 0


@dataclass
class PolylineRecord:
    closed: bool
    layer: int
    width: int
    corners: list[Corner]
    hatch: int = 0
    merge: int = -1
    submerge: int = -1
    source: int = -1
    source_invert: int = 0
    pin: TextRecord | None = None
    description: TextRecord | None = None


@dataclass
class ComponentRecord:
    pin_count: int
    bounds: tuple[int, int, int, int]
    reference: TextRecord
    value: TextRecord
    footprint: TextRecord
    polylines: list[PolylineRecord] = field(default_factory=list)


@dataclass
class CdsDocument:
    options: dict[str, str]
    components: list[ComponentRecord]
    page: str = 'KiCad symbols'


def safe_string(value: str) -> str:
    # ParseKeyString has no backslash-quote escape and trims quoted values.
    if not isinstance(value, str) or not value or value != value.strip() or any(
            c == '"' or ord(c) < 32 or ord(c) == 127 for c in value):
        raise SymbolParseError(f'Unrepresentable CDS string: {value!r}')
    try:
        value.encode('cp1251')
    except UnicodeEncodeError as error:
        raise SymbolParseError(f'CDS string is not CP1251: {value!r}') from error
    return value


def native_integer(value) -> int:
    if type(value) is not int or not -INT_MAX <= value <= INT_MAX:
        raise SymbolParseError(f'CDS value outside signed native integer range: {value!r}')
    return value


def safe_body_text(value: str) -> str:
    safe_string(value)
    # TextList::Draw interprets apostrophe/backtick/pipe and IsCommand detects
    # suffixes/links. This subset accepts literal labels, never command text.
    if any(c in value for c in "'`|~^") or '${' in value or 'PrintableArea' in value or value.endswith(
            ('BLK','BOM','PATH','DATE','ZONE','BLK_PTR')):
        raise SymbolParseError('Graphic text contains native control syntax or unsupported markup')
    return value


def _identifier(value: str, pattern: re.Pattern) -> bool:
    # Native ParsePin converts the numeric suffix with signed-int atoi.
    if not isinstance(value, str) or not pattern.fullmatch(value):
        return False
    suffix = re.search(r'[0-9]+$', value).group()
    return len(suffix) <= 10 and int(suffix) <= INT_MAX


def validate_component(component: ComponentRecord) -> None:
    native_integer(component.pin_count)
    if component.pin_count < 1 or not _identifier(component.reference.value, REFERENCE):
        raise SymbolParseError('CDS profile requires pins and a numbered reference')
    if len(component.bounds) != 4:
        raise SymbolParseError('Invalid CDS rectangle')
    left, bottom, right, top = map(native_integer, component.bounds)
    if left >= right or bottom >= top:
        raise SymbolParseError('Degenerate CDS rectangle')
    texts = [(component.reference, PART_NAME), (component.value, PART_VALUE),
             (component.footprint, FOOTPRINT)]
    terminals, numbers = set(), set()
    for poly in component.polylines:
        for v in (poly.layer, poly.width, poly.hatch, poly.merge, poly.submerge,
                  poly.source, poly.source_invert):
            native_integer(v)
        if poly.layer not in (PART_OUTLINE, PIN_LINE) or poly.width <= 0 or poly.hatch != 0:
            raise SymbolParseError('Unsupported CDS polyline layer/width/hatch')
        if (poly.merge, poly.submerge, poly.source, poly.source_invert) != (-1,-1,-1,0):
            raise SymbolParseError('CDS profile excludes merges, submerges and pictures')
        if len(poly.corners) < (3 if poly.closed else 2):
            raise SymbolParseError('Invalid CDS corner count')
        points = []
        for corner in poly.corners:
            x, y = native_integer(corner.x), native_integer(corner.y)
            if corner.style != 0 or corner.node not in (0,1) or poly.closed and corner.node:
                raise SymbolParseError('Unsupported CDS corner style/node')
            if not left <= x <= right or not bottom <= y <= top:
                raise SymbolParseError('CDS geometry is outside component rectangle')
            points.append((x,y))
        if any(a == b for a,b in zip(points,points[1:])) or poly.closed and points[-1] == points[0]:
            raise SymbolParseError('CDS polyline has collapsed segments')
        if poly.pin is not None:
            if poly.layer != PIN_LINE or poly.closed or len(points) != 2:
                raise SymbolParseError('Pin attribute must attach to one open pin segment')
            if not _identifier(poly.pin.value, PIN_IDENTIFIER) or poly.pin.value in numbers:
                raise SymbolParseError('Invalid/duplicate CDS physical pin number')
            if [c.node for c in poly.corners] != [0,1]:
                raise SymbolParseError('Pin free end must be the final Node=1 corner')
            if points[1] in terminals:
                raise SymbolParseError('CDS pins share a connection terminal')
            terminals.add(points[1])
            numbers.add(poly.pin.value)
            texts.append((poly.pin,PIN_NUMBER))
        elif poly.layer == PIN_LINE or any(c.node for c in poly.corners):
            raise SymbolParseError('CDS pin line/node has no pin number attribute')
        if poly.description is not None:
            if poly.pin is None:
                if poly.layer!=PART_OUTLINE:
                    raise SymbolParseError('Body description has no owning outline')
                safe_body_text(poly.description.value)
            texts.append((poly.description,PIN_DESCRIPTION))
    if len(numbers) != component.pin_count:
        raise SymbolParseError('CDS n_pins does not match attached physical pin records')
    for text, layer in texts:
        safe_string(text.value)
        for v in (text.x,text.y,text.layer,text.angle,text.size,text.width,
                  text.merge,text.submerge,text.font,text.options):
            native_integer(v)
        if text.layer != layer or min(text.size,text.width) < 0 or text.font not in range(12):
            raise SymbolParseError('Invalid CDS text layer/dimensions/font')
        if (text.merge,text.submerge) != (-1,-1):
            raise SymbolParseError('CDS text merge outside profile')
    if '@' in component.value.value or '@' in component.footprint.value:
        raise SymbolParseError('CDS component index reserves @ as value/package separator')


def _tokens(body: str) -> list[str]:
    # Independent lexer: native quoted strings have no escape convention.
    tokens = []
    while body.strip():
        body = body.lstrip()
        if body.startswith('"'):
            end = body.find('"',1)
            if end < 0:
                raise SymbolParseError('Unclosed CDS quoted string')
            tokens.append(body[1:end])
            body = body[end+1:]
            if body and not body[0].isspace():
                raise SymbolParseError('CDS quoted string requires a token boundary')
        else:
            token, _, body = body.partition(' ')
            if '"' in token or any(c.isspace() for c in token):
                raise SymbolParseError('Malformed CDS unquoted token')
            tokens.append(token)
    return tokens


def _ints(tokens: list[str], count: int) -> list[int]:
    if len(tokens) != count or any(not re.fullmatch(r'-?\d+',t) for t in tokens):
        raise SymbolParseError(f'Expected {count} CDS integer fields')
    return [native_integer(int(t)) for t in tokens]


def parse_cds(text: str, *, component_fragment: bool = False) -> CdsDocument:
    """Read the validated straight component subset; unknown records reject.

    A fragment mode exists solely to check the unchanged R3 record extracted
    from detector.cds. It does not claim that a fragment is an importable file.
    """
    options, components = {}, []
    section = 'graphics' if component_fragment else None
    page = 'KiCad symbols'
    current = None
    seen_sections = set()
    active_poly = None
    for line_number,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line or line.startswith('/'):
            continue
        try:
            if line.startswith('['):
                if current is not None or line not in ('[options]','[graphics]','[end]') or line in seen_sections:
                    raise SymbolParseError('Invalid/incomplete CDS section')
                expected = '[options]' if not seen_sections else '[graphics]' if section=='options' else '[end]'
                if component_fragment or line != expected:
                    raise SymbolParseError('Invalid CDS section order')
                seen_sections.add(line)
                section=line[1:-1]
                continue
            key, colon, body=line.partition(':')
            if not colon:
                if line != 'part_end' or current is None:
                    raise SymbolParseError('Unexpected CDS record')
                component=ComponentRecord(current['n_pins'],current['rectangle'],
                    current['ref_des'],current['part_value'],current['footprint_name'],current['polylines'])
                validate_component(component)
                components.append(component)
                current=active_poly=None
                continue
            tokens=_tokens(body)
            if section=='options':
                if key in options or len(tokens)!=1 or key not in {
                    'version','file_version','project_name','units','default_font','default_node_width',
                    'visible_grid_spacing','polyline_grid_spacing','text_grid_spacing'}:
                    raise SymbolParseError('Unsupported/duplicate CDS option')
                options[key]=tokens[0]
            elif section=='graphics':
                if key=='rename_page':
                    if current is not None or components or len(tokens)!=1:
                        raise SymbolParseError('Invalid CDS page declaration')
                    page=safe_string(tokens[0])
                elif key=='n_pins':
                    if current is not None:
                        raise SymbolParseError('Missing CDS part_end')
                    current={'n_pins':_ints(tokens,1)[0],'polylines':[]}
                    active_poly=None
                elif current is None:
                    raise SymbolParseError('CDS geometry/attributes have no component')
                elif key=='rectangle':
                    if key in current:
                        raise SymbolParseError('Duplicate CDS rectangle')
                    current[key]=tuple(_ints(tokens,4))
                elif key in ('ref_des','part_value','footprint_name','pin_name','description'):
                    if len(tokens)!=11:
                        raise SymbolParseError('CDS text requires a string and ten numbers')
                    record=TextRecord(tokens[0],*_ints(tokens[1:],10))
                    if key in ('pin_name','description'):
                        if active_poly is None:
                            raise SymbolParseError('CDS pin attribute has no preceding polyline')
                        attr='pin' if key=='pin_name' else 'description'
                        if getattr(active_poly,attr) is not None:
                            raise SymbolParseError('Duplicate CDS pin attribute')
                        setattr(active_poly,attr,record)
                    else:
                        if key in current or current['polylines']:
                            raise SymbolParseError('Duplicate/late CDS component attribute')
                        current[key]=record
                elif key in ('outline','polyline'):
                    values=_ints(tokens,8)
                    count,hatch,layer,width,merge,submerge,source,invert=values
                    if count < 2 or count > 4096:
                        raise SymbolParseError('CDS corner count outside profile limits')
                    active_poly=PolylineRecord(key=='outline',layer,width,[],hatch,merge,submerge,source,invert)
                    active_poly._expected_count=count
                    current['polylines'].append(active_poly)
                elif key=='corner':
                    if active_poly is None:
                        raise SymbolParseError('Orphan CDS corner')
                    index,x,y,style,node=_ints(tokens,5)
                    if index!=len(active_poly.corners)+1 or index>active_poly._expected_count:
                        raise SymbolParseError('CDS corner order/count mismatch')
                    active_poly.corners.append(Corner(x,y,style,node))
                else:
                    raise SymbolParseError(f'Unsupported CDS record: {key}')
            else:
                raise SymbolParseError('CDS data outside supported section')
        except (ValueError,KeyError) as error:
            raise SymbolParseError(f'CDS line {line_number}: {error}') from error
    if current is not None or not components:
        raise SymbolParseError('Incomplete/empty CDS components')
    for component in components:
        for poly in component.polylines:
            if len(poly.corners)!=poly._expected_count:
                raise SymbolParseError('CDS declared corner count mismatch')
    if not component_fragment:
        if section!='end' or options.get('version')!=TARGET_VERSION or options.get('file_version')!=TARGET_VERSION:
            raise SymbolParseError('CDS profile requires version 1.429 and [end]')
        if options.get('units')!='MM' or 'project_name' not in options:
            raise SymbolParseError('CDS profile requires project_name and MM UI units')
    return CdsDocument(options,components,page)
