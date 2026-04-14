import asyncio

class SystemLogQueue:
    def __init__(self):
        self.queue = asyncio.Queue()

    def push(self, message: str):
        try:
            self.queue.put_nowait(message)
        except Exception:
            pass

    async def get(self):
        return await self.queue.get()

system_logs = SystemLogQueue()
