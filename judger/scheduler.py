import asyncio
import json
import logging
from dataclasses import asdict
from time import time
from typing import List, Optional

from redis.asyncio import Redis

from .client import SandboxClient
from .config import (
    LOGGER_NAME,
    RESULT_QUEUE_NAME,
    TASK_QUEUE_NAME
)
from .judger import Judger
from .models import (
    JudgeStatus,
    Submission,
    SubmissionResult
)

logger = logging.getLogger(f"{LOGGER_NAME}.scheduler")


class Processor:

    def __init__(
        self,
        scheduler: 'Scheduler',
        idx: int,
        redis_url: str,
        sandbox_endpoint: str
    ) -> None:
        self.idx = idx
        self.scheduler: Scheduler = scheduler
        self.redis: Redis = Redis.from_url(redis_url)
        self.client: SandboxClient = SandboxClient(endpoint=sandbox_endpoint)

        logger.debug("Processor %d initialized", self.idx)

    async def __aenter__(self) -> 'Processor':
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self.client.close()
        await self.redis.close()
        logger.debug("Processor %d closed", self.idx)

    async def get_submission(self,) -> Optional[Submission]:
        while self.scheduler.is_running():
            pop_value = await self.redis.blpop(
                TASK_QUEUE_NAME,
                timeout=5
            )
            if pop_value is None:
                continue

            logger.debug(
                "Processor %d get pop up %s",
                self.idx, pop_value
            )
            _, value = pop_value
            return Submission(**json.loads(value))

    async def put_result(self, result: SubmissionResult) -> None:
        logger.debug(
            "Processor %d put result %s",
            self.idx, result
        )
        await self.redis.rpush(
            RESULT_QUEUE_NAME,
            json.dumps(asdict(result))
        )

    async def process(self) -> None:
        submission = await self.get_submission()
        if submission is None:
            return

        logger.debug(
            "Processor %d processing submission %s",
            self.idx, submission
        )
        start_time = time()
        await self.put_result(
            result=SubmissionResult(
                sid=submission.sid,
                judge=JudgeStatus.RunningJudge
            )
        )

        try:
            judger = Judger(self.client, submission)
            result = await judger.get_result()
            await self.put_result(result)

            end_time = time()
            logger.info(
                "Processor %d finished submission %s "
                "with result %s in %f seconds",
                self.idx, submission.sid, result.judge.name,
                (end_time - start_time)
            )

        except Exception as e:
            logger.error(
                "Processor %d failed submission %s with error %s",
                self.idx, submission, e
            )
            await self.put_result(
                SubmissionResult(
                    sid=submission.sid,
                    judge=JudgeStatus.SystemError
                )
            )


class Scheduler:

    def __init__(
        self,
        redis_url: str,
        sandbox_endpoint: str,
        init_concurrent: int = 1
    ) -> None:
        self.redis_url = redis_url
        self.sandbox_endpoint = sandbox_endpoint
        self.init_concurrent = init_concurrent
        self.processors: List[asyncio.Task] = []
        self.running: bool = False

        logger.debug(
            "Scheduler initialized with "
            f"redis_url={self.redis_url}, "
            f"sandbox_endpoint={self.sandbox_endpoint}, "
            f"init_concurrent={self.init_concurrent}"
        )

    def is_running(self) -> bool:
        return self.running

    async def processor(self, idx: int) -> None:
        logger.debug("Processor %d started", idx)

        async with Processor(
            idx=idx,
            scheduler=self,
            redis_url=self.redis_url,
            sandbox_endpoint=self.sandbox_endpoint
        ) as processor:
            while self.running:
                await processor.process()

        logger.debug("Processor %d stopped", idx)

    def start(self) -> None:
        logger.debug("Scheduler starting...")
        self.running = True
        self.processors = [
            asyncio.create_task(self.processor(idx))
            for idx in range(self.init_concurrent)
        ]

    async def wait(self) -> None:
        await asyncio.gather(*self.processors)

    async def stop(self) -> None:
        logger.debug("Scheduler stopping...")
        self.running = False
        await self.wait()
        logger.debug("Scheduler stopped")
