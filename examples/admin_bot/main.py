"""Runnable OpsMesh example wiring opsmesh-adapter-qq with qq_admin plugin."""

import opsmesh
from qq import Adapter

from qq_admin import init_plugin


def main() -> None:
    opsmesh.init()
    driver = opsmesh.get_driver()
    driver.register_adapter(Adapter)
    init_plugin(register_matchers=True)
    opsmesh.run()


if __name__ == "__main__":
    main()
