"""Minimal OpsMesh example demonstrating CurrentGroup dependency injection."""

import opsmesh
from opsmesh import on_command
from qq import GROUP_ADMIN, GROUP_OWNER, Adapter

from qq_admin import CurrentGroup


def main() -> None:
    opsmesh.init()
    opsmesh.get_driver().register_adapter(Adapter)

    info_cmd = on_command(
        "groupinfo", permission=GROUP_OWNER | GROUP_ADMIN, priority=10, block=True
    )

    @info_cmd.handle()
    async def handle_group_info(group: CurrentGroup) -> None:
        info = await group.get_info()
        await info_cmd.finish(f"{info.group_name} (members: {info.group_member_num})")

    opsmesh.run()


if __name__ == "__main__":
    main()
