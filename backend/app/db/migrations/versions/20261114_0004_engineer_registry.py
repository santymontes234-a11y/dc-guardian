"""engineer registry: spec column names, opaque biometric reference, encrypted embeddings

- engineers: engineer_code→engineer_id, email→institutional_email,
  registered_at→registration_date, photo_path→face_embedding_reference (UUID, unique),
  new status ELIMINADO.
- face_embeddings is rebuilt: keyed by subject_ref (no personal data), encrypted embedding,
  no image path (face images are never stored). Pre-existing rows were unencrypted test data
  from before F4 and are discarded.

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.db.types


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUS = sa.Enum('ACTIVO', 'INACTIVO', 'SUSPENDIDO', name='engineerstatus', native_enum=False,
                     create_constraint=True, length=20)
NEW_STATUS = sa.Enum('ACTIVO', 'INACTIVO', 'SUSPENDIDO', 'ELIMINADO', name='engineerstatus', native_enum=False,
                     create_constraint=True, length=20)


def upgrade() -> None:
    op.drop_table('face_embeddings')

    with op.batch_alter_table('engineers', schema=None) as batch_op:
        batch_op.alter_column('engineer_code', new_column_name='engineer_id', existing_type=sa.String(20),
                              existing_nullable=False)
        batch_op.alter_column('email', new_column_name='institutional_email', existing_type=sa.String(120),
                              existing_nullable=False)
        batch_op.alter_column('registered_at', new_column_name='registration_date', existing_nullable=False)
        batch_op.drop_column('photo_path')
        batch_op.add_column(sa.Column('face_embedding_reference', sa.String(length=36), nullable=True))
        batch_op.alter_column('status', type_=NEW_STATUS, existing_type=OLD_STATUS, existing_nullable=False)
        batch_op.drop_constraint('uq_engineers_engineer_code', type_='unique')
        batch_op.drop_constraint('uq_engineers_email', type_='unique')
    # Separate batch: constraints on renamed columns must be created after the rename.
    with op.batch_alter_table('engineers', schema=None) as batch_op:
        batch_op.create_unique_constraint(batch_op.f('uq_engineers_engineer_id'), ['engineer_id'])
        batch_op.create_unique_constraint(batch_op.f('uq_engineers_institutional_email'), ['institutional_email'])
        batch_op.create_unique_constraint(batch_op.f('uq_engineers_face_embedding_reference'),
                                          ['face_embedding_reference'])

    op.create_table('face_embeddings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_ref', sa.String(length=36), nullable=False),
    sa.Column('embedding_encrypted', sa.LargeBinary(), nullable=False),
    sa.Column('model_name', sa.String(length=40), nullable=False),
    sa.Column('quality_score', sa.Float(), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('created_at', app.db.types.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['subject_ref'], ['engineers.face_embedding_reference'],
                            name=op.f('fk_face_embeddings_subject_ref_engineers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_face_embeddings'))
    )
    with op.batch_alter_table('face_embeddings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_face_embeddings_subject_ref'), ['subject_ref'], unique=False)


def downgrade() -> None:
    op.drop_table('face_embeddings')
    op.execute("UPDATE engineers SET status = 'INACTIVO' WHERE status = 'ELIMINADO'")

    with op.batch_alter_table('engineers', schema=None) as batch_op:
        batch_op.drop_constraint('uq_engineers_face_embedding_reference', type_='unique')
        batch_op.drop_constraint('uq_engineers_institutional_email', type_='unique')
        batch_op.drop_constraint('uq_engineers_engineer_id', type_='unique')
        batch_op.alter_column('status', type_=OLD_STATUS, existing_type=NEW_STATUS, existing_nullable=False)
        batch_op.drop_column('face_embedding_reference')
        batch_op.add_column(sa.Column('photo_path', sa.String(length=255), nullable=True))
        batch_op.alter_column('registration_date', new_column_name='registered_at', existing_nullable=False)
        batch_op.alter_column('institutional_email', new_column_name='email', existing_type=sa.String(120),
                              existing_nullable=False)
        batch_op.alter_column('engineer_id', new_column_name='engineer_code', existing_type=sa.String(20),
                              existing_nullable=False)
    with op.batch_alter_table('engineers', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_engineers_email', ['email'])
        batch_op.create_unique_constraint('uq_engineers_engineer_code', ['engineer_code'])

    op.create_table('face_embeddings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('engineer_id', sa.Integer(), nullable=False),
    sa.Column('embedding', sa.LargeBinary(), nullable=False),
    sa.Column('model_name', sa.String(length=40), nullable=False),
    sa.Column('quality_score', sa.Float(), nullable=True),
    sa.Column('source_image_path', sa.String(length=255), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('created_at', app.db.types.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['engineer_id'], ['engineers.id'], name=op.f('fk_face_embeddings_engineer_id_engineers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_face_embeddings'))
    )
    with op.batch_alter_table('face_embeddings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_face_embeddings_engineer_id'), ['engineer_id'], unique=False)
