import pytest
from judger import *

endpoint = 'http://localhost:5050'

testcases = [
    Testcase(
        uuid='82960c11-e8c7-48b5-9cff-d62973570f1e',
        input=MemoryFile("114514\n"),
        output=MemoryFile("\n")
    ),
    Testcase(
        uuid='f66dc244-bf6e-4924-ba17-d5bfae11459c',
        input=MemoryFile("1919810\n"),
        output=MemoryFile("\n")
    ),
]

interactor_code = r"""
#include "testlib.h"
#include <iostream>
using namespace std;
int main(int argc, char** argv) {
  registerInteraction(argc, argv);
  int n = inf.readInt();
  cout.flush();
  int left = 50;
  bool found = false;
  while (left > 0 && !found) {
    left--;
    int a = ouf.readInt(1, 1000000000);
    if (a < n)
      cout << 0 << endl;
    else if (a > n)
      cout << 2 << endl;
    else
      cout << 1 << endl, found = true;
    cout.flush();
  }
  if (!found) quitf(_wa, "couldn't guess the number with 50 questions");
  quitf(_ok, "guessed the number with %d questions!", 50 - left);
}
"""


async def judge_code(code: str, interactor: str = interactor_code) -> SubmissionResult:
    submission = Submission(
        sid=1,
        timeLimit=1000,
        memoryLimit=32768,
        testcases=testcases,
        language=Language.Python,
        code=code,
        type=ProblemType.Interaction,
        additionCode=interactor
    )

    async with SandboxClient(endpoint) as client:
        judger = Judger(client, submission)
        result = await judger.get_result()
    return result


@pytest.mark.asyncio
async def test_interaction_accepted():

    result = await judge_code(r"""
from sys import stdin, stdout

l, r = 1, 1000000000
while l <= r:
    mid = (l + r) // 2
    print(mid)
    stdout.flush()
    res = int(stdin.readline())
    if res == 0:
        l = mid + 1
    elif res == 2:
        r = mid - 1
    else:
        break
""")

    assert result.judge == JudgeStatus.Accepted
    for testcase in result.testcases:
        assert testcase.judge == JudgeStatus.Accepted


@pytest.mark.asyncio
async def test_interaction_wrong_answer():

    result = await judge_code(r"""
from sys import stdout

print(-1)
stdout.flush()
""")

    assert result.judge == JudgeStatus.WrongAnswer
    for testcase in result.testcases:
        assert testcase.judge == JudgeStatus.WrongAnswer


@pytest.mark.asyncio
async def test_interaction_runtime_error():

    result = await judge_code(r"""0/0""")

    assert result.judge == JudgeStatus.RuntimeError
    for testcase in result.testcases:
        assert testcase.judge == JudgeStatus.RuntimeError


@pytest.mark.asyncio
async def test_interaction_bad_interactor():

    result = await judge_code(r"""
from sys import stdin, stdout

l, r = 1, 1000000000
while l <= r:
    mid = (l + r) // 2
    print(mid)
    stdout.flush()
    res = int(stdin.readline())
    if res == 0:
        l = mid + 1
    elif res == 2:
        r = mid - 1
    else:
        break
""", interactor_code.replace(r"quitf(_ok, ", r"return -1; //"))

    assert result.judge == JudgeStatus.SystemError
    for testcase in result.testcases:
        assert testcase.judge == JudgeStatus.SystemError
