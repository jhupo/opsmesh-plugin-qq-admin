"""Runnable OpsMesh example wiring opsmesh-adapter-qq with qq_admin plugin."""

import opsmesh
from qq import Adapter


def main() -> None:
    opsmesh.init()
    driver = opsmesh.get_driver()
    driver.register_adapter(Adapter)
    opsmesh.load_plugin("qq_admin")
    opsmesh.run()


if __name__ == "__main__":
    main()
