"""Local file indexes track the exact Session working-directory value."""
import asyncio

from dsh.context.file_reference_local import LocalFileReferenceService, WorkspaceFileSearch


class AuthorizedFileReferenceService(LocalFileReferenceService):
    inject = ['agents', 'workingDirectory']

    def __init__(self, ctx, config=None):
        self.search_directories = {}
        super().__init__(ctx, config)

    async def list(self, agent, query, signal):
        cwd = await self.ctx.get('workingDirectory').ensure(agent, signal)
        search = self.searches.get(agent)
        if search is None or self.search_directories.get(agent) != cwd:
            if search is not None:
                search.dispose()
                self.retired_searches.add(search)
                async def retire(previous):
                    try:
                        await previous.drain()
                    finally:
                        self.retired_searches.discard(previous)
                task = asyncio.ensure_future(retire(search))
                self.prompt_disposals.add(task)
                task.add_done_callback(self.prompt_disposals.discard)
            search = WorkspaceFileSearch(cwd, self.config)
            self.searches[agent], self.search_directories[agent] = search, cwd
        return await search.list(query, signal)

    def dispose_agent(self, agent):
        self.search_directories.pop(agent, None)
        super().dispose_agent(agent)

    async def dispose(self):
        try:
            await super().dispose()
        finally:
            self.search_directories.clear()
