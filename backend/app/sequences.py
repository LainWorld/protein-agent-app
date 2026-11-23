"""Ground model arguments in the user's text. These rules never select or run a tool."""

from dataclasses import dataclass
import re

from app.schemas import Context

MODELS = re.compile(r'(?<![A-Za-z0-9_])(?:esmfold2|protenix)(?![A-Za-z0-9_])', re.I | re.ASCII)
MODEL_FIELD = re.compile(r'(?:\b(?:use|using)\s+(?:the\s+)?|\bmodel\s*[:=]\s*|(?:改用|换用|使用|用|模型为|模型[：:])\s*)([a-z][\w.-]*)', re.I | re.ASCII)
LABEL = re.compile(r'(?:\bsequence\b|序列)\s*(?:[:：=]|is\b|为|是)\s*', re.I)
MODEL_SUFFIX = re.compile(r'(?:[，,;；。]\s*|\s+)(?:please\s+|请)?(?:using|with|via|使用|改用|换用|用)\s*(?:ESMFold2|Protenix)\s*[.!。！]?\s*$', re.I)
REFER = re.compile(r'\b(same|previous|above|again|instead|it|that sequence|this sequence)\b|同一|同样|相同|上[一面次]|刚才|这[条个]|换用|改用', re.I)
AA = re.compile(r'[ACDEFGHIKLMNPQRSTVWY]+', re.ASCII)


class InputIssue(ValueError):
    pass


def normalize(raw: str) -> str:
    text = raw.strip()
    if '>' in text:
        if text.count('>') != 1 or not text.startswith('>'):
            raise InputIssue('multiple_sequences')
        lines = text.splitlines()
        text = '\n'.join(lines[1:])
    compact = ''.join(text.split())
    if not compact:
        raise InputIssue('empty_sequence')
    if not compact.isascii() or not AA.fullmatch(compact.upper()):
        raise InputIssue('invalid_residues')
    if len(compact) > 500:
        raise InputIssue('too_long')
    return compact.upper()


@dataclass(frozen=True)
class Source:
    raw: str | None = None
    issue: str | None = None
    whole: bool = False
    explicit: bool = False


def locate(text: str) -> Source:
    """Prefer the entire delimited field; never match a model's repaired substring."""
    text = text.strip()
    if text.count('>') > 1 or text.count('```') > 2 or len(LABEL.findall(text)) > 1:
        return Source(issue='multiple_sequences', explicit=True)
    if '```' in text:
        fence = re.fullmatch(r'(.*?)```(?:text|fasta|plaintext)?[ \t]*\r?\n(.*?)```(.*)', text, re.S | re.I)
        if not fence:
            return Source(issue='clarify_sequence', explicit=True)
        if any(has_extra_input(part) for part in (fence[1], fence[3]) if part.strip()):
            return Source(issue='multiple_sequences', explicit=True)
        return Source(fence[2], whole=not (fence[1].strip() or fence[3].strip()), explicit=True)
    if '>' in text:
        before, _, body = text.partition('>')
        if before.rsplit('\n', 1)[-1].strip() or has_extra_input(before):
            return Source(issue='multiple_sequences', explicit=True)
        return Source('>' + body, whole=not before.strip(), explicit=True)
    label = LABEL.search(text)
    if label:
        return Source(MODEL_SUFFIX.sub('', text[label.end():]).strip(), explicit=True)

    # A model or a prose clause can delimit an unlabelled sequence. Keep punctuation,
    # digits and invalid letters inside every candidate. Prefer asking over guessing.
    body = MODEL_SUFFIX.sub('', text)
    parts = re.split(r'[\u3400-\u9fff，。；：！？、]+|\x00', MODELS.sub('\x00', body))
    candidates = []
    for piece in parts:
        field = piece.strip()
        if not field:
            continue
        if MODELS.search(text) and field.lower().strip(' .!?') in {'use', 'instead', 'please', 'try', 'with', 'using'}:
            continue
        # Delimiters belong to an instruction only when there actually is a prefix.
        if field.startswith((':', '=')) and piece != text:
            field = field[1:].lstrip()
        prefixes = list(re.finditer(r'(?:\bsequence\b\s*[:=]?|\bstructure\s+(?:of|for)|^(?:please\s+)?(?:predict|fold|on|for))\s+', field, re.I))
        if prefixes:
            field = field[prefixes[-1].end():].strip()
        if not field:
            continue
        words = field.split()
        if all((w.isascii() and (w.isupper() or not w.isalpha() or AA.fullmatch(w.upper()))) for w in words):
            candidates.append(field)
        elif len(words) == 1 and (len(parts) == 1 or len(field) >= 3) and field.lower() not in {'use', 'using', 'with', 'please', 'switch', 'predict', 'try'}:
            candidates.append(field)
        elif len(parts) == 1 and not MODELS.search(text):
            # No proved boundary between prose and sequence. Validate the whole field
            # if an LLM claims it was input; never search for a valid fragment inside it.
            candidates.append(field)
    if len(candidates) > 1:
        return Source(issue='clarify_sequence')
    return Source(candidates[0], whole=candidates[0] == text) if candidates else Source()


def has_extra_input(text: str) -> bool:
    other = locate(text)
    if other.issue or (other.raw and other.explicit):
        return True
    if other.raw:
        try:
            normalize(other.raw)
            return True
        except InputIssue:
            return any(t.isupper() or any(c.isdigit() for c in t) for t in other.raw.split())
    return False


def instruction_text(text: str) -> str:
    # FASTA headers and fenced sequence contents are data, never a model selection.
    return re.sub(r'```.*?```', '', text, flags=re.S).partition('>')[0]


def named_models(text: str) -> set[str]:
    return {m.group().lower() for m in MODELS.finditer(instruction_text(text))}


def ground_model(text: str, requested: str, src: Source, ctx: Context) -> None:
    named = named_models(text)
    references = {'this','that','my','a','an','it','same','previous','above','following','last','sequence','protein'}
    if any(m[1].lower().rstrip('.') not in {'esmfold2', 'protenix'} | references for m in MODEL_FIELD.finditer(instruction_text(text))):
        raise InputIssue('unsupported_model')
    if len(named) > 1:
        raise InputIssue('clarify_model')
    plain_answer = src.whole or (src.explicit and LABEL.match(text.strip()) is not None)
    if requested not in named and not (not named and plain_answer and ctx.pending_model == requested):
        raise InputIssue('ask_model')


def ground_sequence(text: str, proposed: str, src: Source, ctx: Context) -> str:
    if src.issue:
        raise InputIssue(src.issue)
    # "Use Protenix instead" is a reference, never a fresh protein input. A fresh
    # explicit field (including a bad one) always wins over saved context.
    if src.raw is not None:
        exact = normalize(src.raw)
    elif ctx.pending_sequence and named_models(text):
        exact = ctx.pending_sequence
    elif ctx.last_sequence and REFER.search(text):
        exact = ctx.last_sequence
    else:
        raise InputIssue('ask_sequence' if not (ctx.last_sequence or ctx.pending_sequence) else 'clarify_sequence')
    if normalize(proposed) != exact:
        raise InputIssue('sequence_mismatch')
    return exact
