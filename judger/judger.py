import asyncio
import logging
from typing import List, Optional, Set

from .client import SandboxClient
from .checker import TestlibChecker, DefaultChecker
from .config import LOGGER_NAME
from .language import LanguageRegistry
from .models import (
    JudgeStatus,
    SandboxStatus,
    ProblemType,
    MemoryFile,
    PreparedFile,
    Collector,
    SandboxCmd,
    Testcase,
    Submission,
    TestcaseResult,
    SubmissionResult
)

logger = logging.getLogger(f"{LOGGER_NAME}.judger")


class Judger:

    STATUS_PRIORITY: List[JudgeStatus] = [
        JudgeStatus.SystemError,
        JudgeStatus.OutputLimitExceeded,
        JudgeStatus.MemoryLimitExceeded,
        JudgeStatus.TimeLimitExceeded,
        JudgeStatus.RuntimeError,
        JudgeStatus.WrongAnswer,
        JudgeStatus.PresentationError
    ]

    STATUS_MAP: dict[SandboxStatus, JudgeStatus] = {
        SandboxStatus.MemoryLimitExceeded: JudgeStatus.MemoryLimitExceeded,
        SandboxStatus.TimeLimitExceeded: JudgeStatus.TimeLimitExceeded,
        SandboxStatus.OutputLimitExceeded: JudgeStatus.OutputLimitExceeded,
        SandboxStatus.NonzeroExitStatus: JudgeStatus.RuntimeError,
        SandboxStatus.Signalled: JudgeStatus.RuntimeError
    }

    SKIP_STATUS: Set[JudgeStatus] = {
        JudgeStatus.MemoryLimitExceeded,
        JudgeStatus.TimeLimitExceeded,
        JudgeStatus.OutputLimitExceeded
    }

    def __init__(
        self,
        client: SandboxClient,
        submission: Submission
    ) -> None:
        logger.debug(
            "Initialing Judger with client: %s, submission: %s",
            client, submission
        )
        self.client = client
        self.submission = submission

        self.result = SubmissionResult(
            sid=self.submission.sid,
            judge=JudgeStatus.Pending
        )

        self.compiled_file: Optional[PreparedFile] = None
        self.cleanup_tasks: List[asyncio.Task] = list()

        try:
            self.language = LanguageRegistry.get_config(
                self.submission.language
            )
        except ValueError as e:
            self.result.judge = JudgeStatus.SystemError
            logger.error(
                "Submission %d failed on initialization: "
                "unsupported language %s",
                self.submission.sid,
                self.submission.language
            )

        if self.submission.type == ProblemType.Traditional:
            self.checker = DefaultChecker(client=self.client)
        else:
            self.checker = TestlibChecker(
                client=self.client,
                code=self.submission.additionCode
            )

        logger.debug("Submission %d initialized", self.submission.sid)

    async def compile(self) -> None:
        if self.compiled_file is not None:
            return logger.warning(
                "Submission %d already compiled",
                self.submission.sid
            )
        logger.debug("Submission %d compiling", self.submission.sid)

        try:
            cmd = SandboxCmd(
                args=self.language.compile_cmd,
                files=[
                    MemoryFile(""),
                    Collector("stdout"),
                    Collector("stderr")
                ],
                copyIn={
                    self.language.source_filename:
                        MemoryFile(self.submission.code)
                },
                copyOutCached=[
                    self.language.compiled_filename
                ]
            )
            compiled_result = (
                await self.client.run_command([cmd])
            )[0]

            if compiled_result.status != SandboxStatus.Accepted:
                self.result.judge = JudgeStatus.CompileError
                self.result.error = compiled_result.files.get("stderr", "")
                logger.debug(
                    "Submission %d ended with compile error: %s",
                    self.submission.sid, self.result.error
                )
            else:
                self.compiled_file = PreparedFile(
                    compiled_result.fileIds[self.language.compiled_filename]
                )
                logger.debug("Submission %d compiled", self.submission.sid)

        except Exception as e:
            self.result.judge = JudgeStatus.SystemError
            return logger.error(
                "Submission %d failed on compilation: %s",
                self.submission.sid, e
            )

    async def run_testcase_tradition(
        self,
        testcase: Testcase
    ) -> TestcaseResult:
        logger.debug("Running testcase: '%s'", testcase.uuid)
        result = TestcaseResult(
            uuid=testcase.uuid,
            judge=JudgeStatus.RunningJudge
        )

        def get_runtime_dependencies() -> dict:
            if self.language.need_compile:
                return {
                    self.language.compiled_filename:
                        self.compiled_file
                }
            else:
                return {
                    self.language.source_filename:
                        MemoryFile(self.submission.code)
                }

        timeLimit = 1_000_000 * \
            self.submission.timeLimit * self.language.time_factor
        memoryLimit = 1024 * \
            self.submission.memoryLimit * self.language.memory_factor

        cmd = SandboxCmd(
            args=self.language.run_cmd,
            cpuLimit=timeLimit,
            clockLimit=timeLimit * 2,
            memoryLimit=memoryLimit,
            files=[
                testcase.input,
                Collector("stdout"),
                Collector("stderr")
            ],
            copyIn=get_runtime_dependencies(),
            copyOutCached=[
                "stdout"
            ]
        )
        run_result = (
            await self.client.run_command([cmd])
        )[0]

        result.time = min(run_result.time, timeLimit) // 1_000_000
        result.memory = min(run_result.memory, memoryLimit) // 1024

        output_file = PreparedFile(run_result.fileIds['stdout'])

        if run_result.status == SandboxStatus.Accepted:
            result.judge = await self.checker.check(
                testcase.input, testcase.output, output_file)
        else:
            result.judge = self.STATUS_MAP.get(
                run_result.status, JudgeStatus.SystemError)

        self.cleanup_tasks.append(
            asyncio.create_task(
                self.client.delete_file(output_file.fileId)
            )
        )
        logger.debug(
            "Testcase '%s' finished with judge status: '%s'",
            testcase.uuid, result.judge
        )
        return result

    async def run_testcase_interaction(
        self,
        testcase: Testcase
    ) -> TestcaseResult:
        logger.debug("Running testcase: '%s'", testcase.uuid)
        result = TestcaseResult(
            uuid=testcase.uuid,
            judge=JudgeStatus.RunningJudge
        )

        def get_runtime_dependencies() -> dict:
            if self.language.need_compile:
                return {
                    self.language.compiled_filename:
                        self.compiled_file
                }
            else:
                return {
                    self.language.source_filename:
                        MemoryFile(self.submission.code)
                }

        timeLimit = 1_000_000 * \
            self.submission.timeLimit * self.language.time_factor
        memoryLimit = 1024 * \
            self.submission.memoryLimit * self.language.memory_factor

        cmdUser = SandboxCmd(
            args=self.language.run_cmd,
            cpuLimit=timeLimit,
            clockLimit=timeLimit * 2,
            memoryLimit=memoryLimit,
            files=[
                None, None,
                Collector("stderr")
            ],
            copyIn=get_runtime_dependencies(),
        )
        cmdInteractor = SandboxCmd(
            args=[
                './Interactor', 'infile', 'outfile', 'ansfile'
            ],
            files=[
                None, None,
                Collector("stderr")
            ],
            copyIn={
                "Interactor": self.checker.compiled_file,
                "infile": testcase.input,
                "outfile": MemoryFile(""),
                "ansfile": testcase.output
            }
        )

        run_results = await self.client.run_command(
            [cmdUser, cmdInteractor],
            [
                {"in": {"index": 0, "fd": 1},
                 "out": {"index": 1, "fd": 0}},
                {"in": {"index": 1, "fd": 1},
                 "out": {"index": 0, "fd": 0}}
            ]
        )
        user_result, interactor_result = run_results

        result.time = min(user_result.time, timeLimit) // 1_000_000
        result.memory = min(user_result.memory, memoryLimit) // 1024

        if user_result.status != SandboxStatus.Accepted:
            result.judge = self.STATUS_MAP.get(
                user_result.status, JudgeStatus.SystemError)

        elif interactor_result.status == SandboxStatus.Accepted:
            result.judge = JudgeStatus.Accepted

        elif interactor_result.status == SandboxStatus.NonzeroExitStatus:
            if interactor_result.exitStatus == 1:
                result.judge = JudgeStatus.WrongAnswer
            elif interactor_result.exitStatus == 2:
                result.judge = JudgeStatus.PresentationError
            else:
                logger.error(
                    "Interactor exited with unexpected exit status: %d",
                    interactor_result.exitStatus
                )
                result.judge = JudgeStatus.SystemError

        else:
            logger.error(
                "Interactor execution failed with status: %s",
                interactor_result.status
            )
            result.judge = JudgeStatus.SystemError

        logger.debug(
            "Testcase '%s' finished with judge status: '%s'",
            testcase.uuid, result.judge
        )
        return result

    async def run_testcase(self, testcase: Testcase) -> TestcaseResult:
        if self.submission.type == ProblemType.Interaction:
            return await self.run_testcase_interaction(testcase)
        else:
            return await self.run_testcase_tradition(testcase)

    async def cleanup(self) -> None:
        logger.debug("Submission %d cleanup started", self.submission.sid)

        if self.compiled_file is not None:
            self.cleanup_tasks.append(
                asyncio.create_task(
                    self.client.delete_file(self.compiled_file.fileId)
                )
            )
        await asyncio.gather(*self.cleanup_tasks)
        self.cleanup_tasks.clear()

        logger.debug("Submission %d cleanup completed", self.submission.sid)

    async def run(self) -> None:
        if self.result.judge != JudgeStatus.Pending:
            return logger.warning(
                "Submission %d result already set: %s",
                self.submission.sid, self.result.judge
            )
        logger.debug("Submission %d start judging", self.submission.sid)

        if self.language.need_compile:
            await self.compile()
            if self.result.judge != JudgeStatus.Pending:
                return
            elif self.compiled_file is None:
                self.result.judge = JudgeStatus.SystemError
                return logger.error(
                    "Submission %d failed on compilation: no compiled file",
                    self.submission.sid
                )

        if len(self.submission.testcases) == 0:
            self.result.judge = JudgeStatus.SystemError
            return logger.error(
                "Submission %d failed on judging: no testcases",
                self.submission.sid
            )

        try:
            await self.checker.compile()
        except Exception as e:
            self.result.judge = JudgeStatus.SystemError
            return logger.error(
                "Submission %d failed on checker compilation: %s",
                self.submission.sid, e
            )

        skipped = False
        for testcase in self.submission.testcases:
            if skipped:
                testcase_result = TestcaseResult(
                    uuid=testcase.uuid,
                    judge=JudgeStatus.Skipped
                )
            else:
                try:
                    testcase_result = await self.run_testcase(testcase)
                except Exception as e:
                    testcase_result = TestcaseResult(
                        uuid=testcase.uuid,
                        judge=JudgeStatus.SystemError
                    )
                    logger.error(
                        "Submission %d failed on testing '%s': %s",
                        self.submission.sid, testcase.uuid, e
                    )
            self.result.testcases.append(testcase_result)

            if testcase_result.judge in self.SKIP_STATUS:
                skipped = True

        if len(self.result.testcases) == 0:
            self.result.judge = JudgeStatus.SystemError
            return logger.error(
                "Submission %d failed on judging: no testcase results",
                self.submission.sid
            )

        self.result.time = max(
            testcase.time for testcase in self.result.testcases
        )
        self.result.memory = max(
            testcase.memory for testcase in self.result.testcases
        )

        if all(
            testcase.judge == JudgeStatus.Accepted
            for testcase in self.result.testcases
        ):
            self.result.judge = JudgeStatus.Accepted
        else:
            for status in self.STATUS_PRIORITY:
                if any(
                    testcase.judge == status
                    for testcase in self.result.testcases
                ):
                    self.result.judge = status
                    break
            else:
                self.result.judge = JudgeStatus.SystemError
                return logger.error(
                    "Submission %d failed on final check: no status found",
                    self.submission.sid
                )

    async def get_result(self) -> SubmissionResult:
        if self.result.judge == JudgeStatus.Pending:
            try:
                await self.run()
            except Exception as e:
                self.result.judge = JudgeStatus.SystemError
                logger.error(
                    "Submission %d failed on judging: %s",
                    self.submission.sid, e
                )
            try:
                await self.cleanup()
            except Exception as e:
                logger.error(
                    "Submission %d failed on cleanup: %s",
                    self.submission.sid, e
                )
        logger.debug(
            "Submission %d result: %s",
            self.submission.sid, self.result
        )
        return self.result
