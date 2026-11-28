"""Minimal automatic QQ group administration bot using OpsMesh + qq_admin."""

import opsmesh
import qq


def main() -> None:
    opsmesh.init()
    opsmesh.register_adapter(qq.Adapter)
    opsmesh.load_plugin("qq_admin")
    opsmesh.run()


if __name__ == "__main__":
    main()
