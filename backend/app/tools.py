"""Tool schema and dispatch. Only these two functions are available to the LLM."""

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas import Context, FoldModel
from app.sequences import InputIssue, Source, ground_model, ground_sequence, named_models
from app.jobs import Submission


class PredictArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sequence: str = Field(min_length=1, max_length=4000, description='Exact user-supplied single-chain amino acid sequence; never repair it.')
    model: FoldModel


class StatusArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: UUID


def tool(name, description, schema):
    return {'type': 'function', 'function': {'name': name, 'description': description,
                                             'parameters': schema.model_json_schema()}}


TOOLS = [tool('predict_structure', 'Submit after user supplies both exact sequence and a supported model. Return server receipt.', PredictArgs),
         tool('get_job_status', 'Read one job by its UUID in this conversation.', StatusArgs)]


def dispatch(name: str, args: dict, text: str, cid: UUID, ctx: Context, src: Source, jobs: Submission) -> dict:
    try:
        if name == 'predict_structure':
            if 'model' in args and args['model'] not in ('esmfold2', 'protenix'):
                raise InputIssue('unsupported_model')
            if not (set(args) - {'sequence', 'model'}):
                if 'sequence' not in args and args.get('model') in ('esmfold2', 'protenix'):
                    if named_models(text) == {args['model']}:
                        ctx.pending_model, ctx.pending_sequence = args['model'], None
                    return {'code': 'ask_sequence'}
                if 'model' not in args and isinstance(args.get('sequence'), str):
                    seq = ground_sequence(text, args['sequence'], src, ctx)
                    ctx.pending_sequence, ctx.pending_model = seq, None
                    return {'code': 'ask_model', 'length': len(seq)}
            p = PredictArgs.model_validate(args)
            try:
                seq = ground_sequence(text, p.sequence, src, ctx)
            except InputIssue as issue:
                if str(issue) == 'ask_sequence' and named_models(text) == {p.model}:
                    ctx.pending_model, ctx.pending_sequence = p.model, None
                raise
            try:
                ground_model(text, p.model, src, ctx)
            except InputIssue as issue:
                if str(issue) in {'ask_model', 'clarify_model', 'unsupported_model'}:
                    ctx.pending_sequence, ctx.pending_model = seq, None
                    return {'code': str(issue), 'length': len(seq)}
                raise
            receipt = jobs.submit(seq, p.model)
            ctx.last_sequence, ctx.pending_sequence, ctx.pending_model = seq, None, None
            return receipt
        if name == 'get_job_status':
            p = StatusArgs.model_validate(args)
            explicit_ids = {UUID(x) for x in re.findall(r'(?<![\da-f])[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}(?![\da-f])', text, re.I | re.ASCII)}
            known = jobs.store.job_ids(cid)
            # An explicit ID wins over a model's guess; an implicit status query can
            # default only to this conversation's latest job, as specified in the design.
            if (explicit_ids and explicit_ids != {p.job_id}) or (not explicit_ids and (not known or p.job_id != known[-1])):
                return {'code': 'ask_job'}
            return jobs.status(cid, p.job_id)
        return {'code': 'unknown_tool'}
    except InputIssue as issue:
        return {'code': str(issue)}
    except ValidationError:
        return {'code': 'invalid_tool_args'}


# A closed vocabulary prevents a free-text LLM claim from turning into a job status
# or download link. The LLM chooses the dialogue act; the server owns the facts.
MESSAGES = {
    'openprotein_config': ('请在后端填写 OPENPROTEIN_USERNAME 和 OPENPROTEIN_PASSWORD，然后重启服务。',
                           'Configure OPENPROTEIN_USERNAME and OPENPROTEIN_PASSWORD on the backend, then restart.'),
    'biohub_config': ('ESMFold2 Real 未就绪。请核对后端的 Biohub API key、官方地址和 Fast 模型名，然后重启后端。没有创建任务。',
                      'ESMFold2 Real needs the Biohub API key, official URL and Fast model ID. Check the backend settings and restart. No job was created.'),
    'help': ('我可以核对一条蛋白质序列，并按你指定的 ESMFold2 或 Protenix 准备预测请求。请给我序列和模型。', 'Send one protein sequence and choose ESMFold2 or Protenix. I can check the input and prepare the request.'),
    'ask_model': ('请选择一个预测模型：ESMFold2 或 Protenix。', 'Which model would you like: ESMFold2 or Protenix?'),
    'ask_sequence': ('请提供一条蛋白质氨基酸序列，可直接粘贴原始序列或单条 FASTA。', 'Please provide one protein amino acid sequence, as raw text or a single FASTA record.'),
    'clarify_sequence': ('我无法唯一确定你指的是哪条序列。请单独粘贴完整的一条序列，或明确说“同一条序列”。', 'Which sequence do you mean? Paste one complete sequence on its own, or explicitly refer to the same sequence.'),
    'clarify_model': ('这次需要选定一个模型。请确认是 ESMFold2 还是 Protenix。', 'Please select just one model for this request: ESMFold2 or Protenix.'),
    'unsupported_model': ('目前只支持 ESMFold2 和 Protenix。请重新指定一个；未提交任务。', 'Only ESMFold2 and Protenix are supported. Please choose one; no job was submitted.'),
    'multiple_sequences': ('一次只能提交一条序列或一条 FASTA 记录，请分开发送。', 'Please send one sequence or one FASTA record at a time.'),
    'empty_sequence': ('序列为空。请在 FASTA 标题下一行填写序列，或粘贴原始序列。', 'The sequence is empty. Add residues below the FASTA header or paste a raw sequence.'),
    'invalid_residues': ('序列包含非法残基或符号。只接受 20 种标准氨基酸；请核对原文，系统不会自动删除或替换字符。', 'The sequence contains an invalid residue or symbol. Only the 20 standard amino acids are accepted; nothing was repaired.'),
    'too_long': ('单条序列当前上限为 500 aa，未提交任务。', 'The current application limit is 500 amino acids per sequence. No job was submitted.'),
    'sequence_mismatch': ('工具提出的序列与原文或本会话确认的序列不一致，已拒绝。请重新粘贴原序列。', 'The proposed sequence did not match your input or confirmed conversation history. Please paste the exact sequence again.'),
    'no_jobs': ('本会话尚未创建预测任务，没有可查询的状态。', 'This conversation has no prediction jobs to check.'),
    'ask_job': ('请提供本会话的任务编号，或说明要查询哪一个任务。', 'Which job in this conversation do you mean? Please provide its ID.'),
    'job_not_found': ('本会话中没有找到该任务编号。', 'That job ID was not found in this conversation.'),
    'invalid_tool_args': ('模型给出的工具参数不完整或格式有误。请补充序列、模型或任务编号。', 'The tool arguments were missing or invalid. Please check the sequence, model or job ID.'),
    'unknown_tool': ('模型请求了不支持的工具。该调用已拒绝。', 'The model requested an unsupported tool. The call was rejected.'),
    'call_conflict': ('工具调用编号重复但参数冲突，已拒绝重复执行。', 'A repeated tool call ID had conflicting arguments. It was not executed.'),
}


def render(result: dict, lang: Literal['en', 'zh']) -> str:
    code, en = result['code'], lang == 'en'
    if code == 'real_unavailable':
        return ('Protenix Real needs the Mini model ID and an executable official CLI on the backend host. Check PROTENIX_EXECUTABLE and PROTENIX_MODEL.'
                if en else 'Protenix Real 未就绪。请核对后端的 PROTENIX_EXECUTABLE 路径与 PROTENIX_MODEL 的 Mini 型号，然后重启。')
    if code == 'job_submitted':
        model = {'esmfold2': 'ESMFold2', 'protenix': 'Protenix'}[result['model']]
        length, jid = result['length'], result['id']
        if result['mode'] == 'real':
            executor = 'Protenix CLI'
            if result['model'] == 'esmfold2':
                executor = 'OpenProtein' if result['model_version'] == 'esmfold2' else 'Biohub'
            return (f'{model} · Real · {length} aa. Job {jid} queued for {executor}.' if en else
                    f'{model} · Real · {length} aa。任务 {jid} 已排队，将由 {executor} 执行。')
        return (f'{model} · Mock · {length} aa. Submitted job {jid}. The example is RCSB PDB 1UBQ, not a prediction for your sequence.' if en else
                f'{model} · Mock · {length} aa。已提交任务 {jid}。使用 RCSB PDB 1UBQ 示例结构，非输入序列的真实预测。')
    if code == 'job_status':
        text = (f"Job {result['id']}: " if en else f"任务 {result['id']}：") + f"{result['status']} ({result['model']}, {result['mode']})"
        if result.get('error'):
            text += ' · ' + (result['error'] if en else result['error_message'])
        if result['mode'] == 'mock':
            text += ' · 1UBQ example, not an input-specific prediction.' if en else ' · 1UBQ 示例结构，非输入序列的真实预测。'
        return text
    msg = MESSAGES[code][int(en)]
    if code == 'ask_model' and 'length' in result:
        msg = (f"Received {result['length']} aa. " if en else f"已收到 {result['length']} aa 序列。") + msg
    return msg
