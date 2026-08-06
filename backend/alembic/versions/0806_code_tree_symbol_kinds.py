"""Expand library symbols for the code-tree API documentation.

Revision ID: 0806codetree
Revises: 0805libsymbols
Create Date: 2026-08-05 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0806codetree"
down_revision: Union[str, None] = "0805libsymbols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("library_symbol") as batch_op:
        batch_op.drop_constraint("ck_library_symbol_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_library_symbol_kind",
            "kind IN ('class', 'struct', 'interface', 'enum', 'function', 'constructor', 'method', 'field', 'property', 'constant', 'enum_value')",
        )


def downgrade() -> None:
    with op.batch_alter_table("library_symbol") as batch_op:
        batch_op.drop_constraint("ck_library_symbol_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_library_symbol_kind",
            "kind IN ('class', 'struct', 'interface', 'enum', 'function', 'method', 'property', 'constant')",
        )
