import logging
from hashlib import sha256
from pathlib import Path
from typing import List, Optional, Union

from .client import SandboxClient
from .config import DEFAULT_CHECKER, LOGGER_NAME, TESTLIB_PATH
from .models import (
    JudgeStatus,
    SandboxStatus,
    LocalFile,
    MemoryFile,
    PreparedFile,
    Collector,
    SandboxCmd,
)

logger = logging.getLogger(f"{LOGGER_NAME}.checker")


class TestlibChecker:

    SOURCE_FILENAME: str = "Checker.cpp"
    COMPILED_FILENAME: str = "Checker"
    COMPILE_CMD: List[str] = [
        "/usr/bin/g++-12", "Checker.cpp", "-o", "Checker",
        "-std=c++17", "-O2", "-lm", "-w", "-fmax-errors=3", "--static"
    ]
    RUN_CMD: List[str] = [
        "./Checker", "infile", "outfile", "ansfile"
    ]

    def __init__(
        self,
        client: SandboxClient,
        code: str
    ) -> None:
        self.client = client
        self.code = code
        self.compiled_file: Optional[PreparedFile] = None

        logger.debug("Testlib checker initialized")

    async def compile(self) -> None:
        if self.compiled_file is not None:
            return

        checker_hash = sha256(self.code.encode()).hexdigest()
        identifier = f"checker-{checker_hash}"

        self.compiled_file = await self.client.cache.get(identifier)
        if self.compiled_file is not None:
            logger.debug("Get compiled checker from cache")
            return

        logger.debug("Compiling checker")

        testlib_file = await self.client.cache.get("testlib.h")
        if testlib_file is None:
            logger.debug("Testlib header file not found in cache")

            if not TESTLIB_PATH.exists():
                raise FileNotFoundError(
                    "Testlib header file not found: %s" %
                    TESTLIB_PATH
                )
            with open(TESTLIB_PATH, 'rt', encoding='utf-8') as f:
                testlib_code = f.read()

            testlib_file = await self.client.upload_file(
                content=testlib_code, filename="testlib.h")
            await self.client.cache.set("testlib.h", testlib_file)
            logger.debug("Uploaded testlib header file")

        cmd = SandboxCmd(
            args=self.COMPILE_CMD,
            files=[
                MemoryFile(""),
                Collector("stdout"),
                Collector("stderr")
            ],
            copyIn={
                self.SOURCE_FILENAME: MemoryFile(self.code),
                "testlib.h": testlib_file
            },
            copyOutCached=[
                self.COMPILED_FILENAME
            ]
        )
        compiled_result = (
            await self.client.run_command([cmd])
        )[0]

        if compiled_result.status != SandboxStatus.Accepted:
            raise RuntimeError(
                "Failed to compile Testlib checker: \n%s" %
                compiled_result.files.get("stderr", "")
            )
        self.compiled_file = PreparedFile(
            compiled_result.fileIds[self.COMPILED_FILENAME])
        await self.client.cache.set(identifier, self.compiled_file)

    async def check(
        self,
        input_file: Union[LocalFile, MemoryFile, PreparedFile],
        answer_file: Union[LocalFile, MemoryFile, PreparedFile],
        output_file: Union[LocalFile, MemoryFile, PreparedFile]
    ) -> JudgeStatus:
        logger.debug(
            "Checking with 'infile': %s, 'outfile': %s, 'ansfile': %s",
            input_file, output_file, answer_file
        )
        await self.compile()

        cmd = SandboxCmd(
            args=self.RUN_CMD,
            files=[
                MemoryFile(""),
                Collector("stdout"),
                Collector("stderr")
            ],
            copyIn={
                self.COMPILED_FILENAME: self.compiled_file,
                "infile": input_file,
                "outfile": output_file,
                "ansfile": answer_file
            }
        )
        checker_result = (
            await self.client.run_command([cmd])
        )[0]

        logger.debug("Checker result: %s", checker_result)

        if checker_result.status == SandboxStatus.Accepted:
            return JudgeStatus.Accepted

        elif checker_result.status == SandboxStatus.NonzeroExitStatus:
            return JudgeStatus.WrongAnswer

        else:
            logger.error(
                "Checker execution failed with status: %s",
                checker_result.status
            )
            return JudgeStatus.SystemError


class DefaultChecker(TestlibChecker):

    RUN_CMD: List[str] = [
        "./Checker", "tc.in", 'tc.out', 'user.out'
    ]

    def __init__(
        self,
        client: SandboxClient,
        code_file: Union[str, Path] = DEFAULT_CHECKER
    ) -> None:
        self.client = client
        self.compiled_file: Optional[PreparedFile] = None

        try:
            with open(code_file, 'rt', encoding='utf-8') as f:
                self.code = f.read()
        except FileNotFoundError as e:
            raise FileNotFoundError(
                "Checker code file not found: %s" %
                code_file
            ) from e

        logger.debug(
            "Checker initialized with code file: '%s'",
            code_file
        )

    async def check(
        self,
        input_file: Union[LocalFile, MemoryFile, PreparedFile],
        output_file: Union[LocalFile, MemoryFile, PreparedFile],
        user_file: Union[LocalFile, MemoryFile, PreparedFile]
    ) -> JudgeStatus:
        logger.debug(
            "Checking with 'tc.in': %s, 'tc.out': %s, 'user.out': %s",
            input_file, output_file, user_file
        )
        await self.compile()

        cmd = SandboxCmd(
            args=self.RUN_CMD,
            files=[
                MemoryFile(""),
                Collector("stdout"),
                Collector("stderr")
            ],
            copyIn={
                self.COMPILED_FILENAME: self.compiled_file,
                "tc.in": input_file,
                "tc.out": output_file,
                "user.out": user_file
            }
        )
        checker_result = (
            await self.client.run_command([cmd])
        )[0]

        if checker_result.status == SandboxStatus.Accepted:
            return JudgeStatus.Accepted

        elif checker_result.status == SandboxStatus.NonzeroExitStatus:
            if checker_result.exitStatus == 1:
                return JudgeStatus.WrongAnswer
            elif checker_result.exitStatus == 2:
                return JudgeStatus.PresentationError
            else:
                logger.error(
                    "Checker exited with unknown exit code: %d",
                    checker_result.exitStatus
                )
                return JudgeStatus.SystemError

        else:
            logger.error(
                "Checker execution failed with status: %s",
                checker_result.status
            )
            return JudgeStatus.SystemError
