import pytest
from judger import *

endpoint = 'http://localhost:5050'


YESNO_CHECKER = r"""
#include "testlib.h"
#include <string>

using namespace std;

const string YES = "YES";
const string NO = "NO";

int main(int argc, char *argv[]) {
    setName("%s", (YES + " or " + NO + " (case insensitive)").c_str());
    registerTestlibCmd(argc, argv);

    std::string ja = upperCase(ans.readWord());
    std::string pa = upperCase(ouf.readWord());

    if (ja != YES && ja != NO)
        quitf(_fail, "%s or %s expected in answer, but %s found", YES.c_str(), NO.c_str(), compress(ja).c_str());

    if (pa != YES && pa != NO)
        quitf(_pe, "%s or %s expected, but %s found", YES.c_str(), NO.c_str(), compress(pa).c_str());

    if (ja != pa)
        quitf(_wa, "expected %s, found %s", compress(ja).c_str(), compress(pa).c_str());

    quitf(_ok, "answer is %s", ja.c_str());
}
"""


@pytest.mark.asyncio
async def test_empty_testcases():
    submission = Submission(
        sid=1,
        timeLimit=1000,
        memoryLimit=32768,
        testcases=[],
        language=Language.Python,
        code='print("Hello, World!")'
    )

    async with SandboxClient(endpoint) as client:
        judger = Judger(client, submission)
        result = await judger.get_result()
    assert result.judge == JudgeStatus.SystemError
    assert len(result.testcases) == 0


@pytest.mark.asyncio
async def test_special_judge_accepted():
    submission = Submission(
        sid=1,
        timeLimit=1000,
        memoryLimit=32768,
        testcases=[Testcase(
            uuid='bab33078-ea14-46ff-93bc-3a5a6c19fda6',
            input=MemoryFile('1 1 2\n'),
            output=MemoryFile('YES\n')
        )],
        language=Language.Python,
        code="\n".join([
            "a, b, c = map(int, input().split())",
            "print('YES' if a + b == c else 'NO')"]),
        type=ProblemType.SpecialJudge,
        additionCode=YESNO_CHECKER
    )

    async with SandboxClient(endpoint) as client:
        judger = Judger(client, submission)
        result = await judger.get_result()
    assert result.judge == JudgeStatus.Accepted
    for testcase in result.testcases:
        assert testcase.judge == JudgeStatus.Accepted


@pytest.mark.asyncio
async def test_special_judge_wrong_answer():
    submission = Submission(
        sid=1,
        timeLimit=1000,
        memoryLimit=32768,
        testcases=[Testcase(
            uuid='bab33078-ea14-46ff-93bc-3a5a6c19fda6',
            input=MemoryFile('1 1 2\n'),
            output=MemoryFile('YES\n')
        )],
        language=Language.Python,
        code="print('NO')",
        type=ProblemType.SpecialJudge,
        additionCode=YESNO_CHECKER
    )

    async with SandboxClient(endpoint) as client:
        judger = Judger(client, submission)
        result = await judger.get_result()
    assert result.judge == JudgeStatus.WrongAnswer
    for testcase in result.testcases:
        assert testcase.judge == JudgeStatus.WrongAnswer


@pytest.mark.asyncio
async def test_special_judge_checker_compile_error():
    submission = Submission(
        sid=1,
        timeLimit=1000,
        memoryLimit=32768,
        testcases=[Testcase(
            uuid='bab33078-ea14-46ff-93bc-3a5a6c19fda6',
            input=MemoryFile('1 1 2\n'),
            output=MemoryFile('WHATEVER\n')
        )],
        language=Language.Python,
        code="import this",
        type=ProblemType.SpecialJudge,
        additionCode=r"¯\_(ツ)_/¯"
    )

    async with SandboxClient(endpoint) as client:
        judger = Judger(client, submission)
        result = await judger.get_result()
    assert result.judge == JudgeStatus.SystemError
    for testcase in result.testcases:
        assert testcase.judge == JudgeStatus.SystemError
