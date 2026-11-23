from uuid import uuid4

import pytest

from app.schemas import Context
from app.sequences import InputIssue, ground_model, ground_sequence, locate, normalize
from app.tools import dispatch
from unittest.mock import Mock


@pytest.mark.parametrize(('raw','expected'), [('\na cD\tE','ACDE'),('>1UBQ | desc\r\naC d\r\nE','ACDE'),
    ('a','A'),('m'*500,'M'*500)])
def test_allowed_normalization(raw,expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(('raw','code'), [('', 'empty_sequence'),('>only a header','empty_sequence'),
    ('ABCZ123','invalid_residues'),('ACD-EF','invalid_residues'),('ACDX','invalid_residues'),('ACD*','invalid_residues'),
    ('AßC','invalid_residues'),('ＡCDE','invalid_residues'),('m'*501,'too_long'),('>a\nAA\n>b\nCC','multiple_sequences')])
def test_raw_rejections(raw,code):
    with pytest.raises(InputIssue,match=code): normalize(raw)


@pytest.mark.parametrize('text', ['请用 ESMFold2 预测 ACDE','Predict the structure of ACDE using ESMFold2',
    'Use ESMFold2. Sequence: a c\nD e', 'ESMFold2\n>desc\nACDE', 'ESMFold2\n```fasta\n>desc\nACDE\n```'])
def test_verbatim_fields_in_conversation(text):
    src,ctx=locate(text),Context()
    assert ground_sequence(text,'ACDE',src,ctx) == 'ACDE'
    ground_model(text,'esmfold2',src,ctx)


@pytest.mark.parametrize(('text','offered','code'), [
    ('Use ESMFold2. Sequence: ACDEFG','ACDE','sequence_mismatch'),
    ('Use ESMFold2. Sequence: ABCZ123','AC','invalid_residues'),
    ('ESMFold2\n>one\nACD\n>two\nEFG','ACD','multiple_sequences'),
    ('ESMFold2\nACD\n>two\nEFG','EFG','multiple_sequences'),
    ('ACD>two\nEFG','EFG','multiple_sequences'),
    ('ESMFold2\n```\nACD\n```\n```\nEFG\n```','ACD','multiple_sequences'),
    ('ESMFold2\nACDE-FG','ACDEFG','invalid_residues'),
    ('同一序列改用 Protenix，序列：ABCZ123','ACDE','invalid_residues'),
    ('Protenix\n>empty','ACDE','empty_sequence'),
    ('Protenix\n'+ 'A'*501,'A'*500,'too_long'),
    ('请用 Protenix 预测：ACD，EFG','ACD','clarify_sequence'),
    ('Protenix\n>example\nACDE','ACDF','sequence_mismatch')])
def test_never_uses_a_repaired_or_old_sequence(text,offered,code):
    with pytest.raises(InputIssue,match=code):
        ground_sequence(text,offered,locate(text),Context(last_sequence='ACDE',pending_sequence='ACDE'))


@pytest.mark.parametrize(('text','code'), [('>ESMFold2\nACDE','ask_model'),
    ('Using AlphaFold. Sequence: ACDE','unsupported_model'),('用 AlphaFold 预测：ACDE','unsupported_model'),
    ('ESMFold2 or Protenix. Sequence: ACDE','clarify_model')])
def test_model_must_be_selected_by_user(text,code):
    with pytest.raises(InputIssue,match=code): ground_model(text,'esmfold2',locate(text),Context())


@pytest.mark.parametrize(('name','args','code'), [('no_such_tool',{},'unknown_tool'),
    ('predict_structure',{'sequence':'ACDE','model':'alphafold'},'unsupported_model'),
    ('predict_structure',{'sequence':'ACDE','model':'protenix','extra':'ignored?'},'invalid_tool_args'),
    ('predict_structure',{'sequence':['ACDE'],'model':'protenix'},'invalid_tool_args'),
    ('get_job_status',{'job_id':'bad'},'invalid_tool_args')])
def test_rejected_arguments_never_reach_job_service(tmp_path, name,args,code):
    service = Mock()
    text='请用 Protenix 预测序列：ACDE'
    assert dispatch(name,args,text,uuid4(),Context(),locate(text),service)['code'] == code
    service.submit.assert_not_called()
