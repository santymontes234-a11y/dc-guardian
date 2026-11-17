"""QR credentials, main-entrance events/signals and DHT11 environment readings

- qr_credentials: one ACTIVA credential per engineer at most; only sha256(token) is stored.
- entrance_events: every QR scan at ENTRADA_PRINCIPAL (bitácora) + its one-shot LED signal.
- environment_readings: DHT11 readings of the server room (purged after 7 days).
(docs/contrato-qr-dht11.md)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17 13:49:16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.db.types


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('environment_readings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('temperature_c', sa.Float(), nullable=True),
    sa.Column('humidity_pct', sa.Float(), nullable=True),
    sa.Column('sensor', sa.Enum('OK', 'ERROR', name='sensorreading', native_enum=False, create_constraint=True, length=10), nullable=False),
    sa.Column('fan', sa.Boolean(), nullable=False),
    sa.Column('alarm', sa.Boolean(), nullable=False),
    sa.Column('conditions', sa.String(length=120), nullable=False),
    sa.Column('created_at', app.db.types.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['areas.id'], name=op.f('fk_environment_readings_area_id_areas')),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], name=op.f('fk_environment_readings_device_id_devices'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_environment_readings'))
    )
    with op.batch_alter_table('environment_readings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_environment_readings_created_at'), ['created_at'], unique=False)
        batch_op.create_index('ix_envreading_device_at', ['device_id', 'created_at'], unique=False)

    op.create_table('qr_credentials',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('engineer_id', sa.Integer(), nullable=False),
    sa.Column('token_sha256', sa.String(length=64), nullable=False),
    sa.Column('prefix', sa.String(length=6), nullable=False),
    sa.Column('status', sa.Enum('ACTIVA', 'REVOCADA', name='qrstatus', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('expires_at', app.db.types.UTCDateTime(), nullable=True),
    sa.Column('created_at', app.db.types.UTCDateTime(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('last_used_at', app.db.types.UTCDateTime(), nullable=True),
    sa.Column('revoked_at', app.db.types.UTCDateTime(), nullable=True),
    sa.Column('revoked_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['admins.id'], name=op.f('fk_qr_credentials_created_by_admins')),
    sa.ForeignKeyConstraint(['engineer_id'], ['engineers.id'], name=op.f('fk_qr_credentials_engineer_id_engineers')),
    sa.ForeignKeyConstraint(['revoked_by'], ['admins.id'], name=op.f('fk_qr_credentials_revoked_by_admins')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_qr_credentials')),
    sa.UniqueConstraint('token_sha256', name=op.f('uq_qr_credentials_token_sha256'))
    )
    with op.batch_alter_table('qr_credentials', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_qr_credentials_engineer_id'), ['engineer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_qr_credentials_status'), ['status'], unique=False)

    op.create_table('entrance_events',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('device_id', sa.Integer(), nullable=True),
    sa.Column('engineer_id', sa.Integer(), nullable=True),
    sa.Column('qr_credential_id', sa.Integer(), nullable=True),
    sa.Column('request_id', sa.Integer(), nullable=True),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('result', sa.String(length=10), nullable=False),
    sa.Column('reason_code', sa.String(length=40), nullable=True),
    sa.Column('created_at', app.db.types.UTCDateTime(), nullable=False),
    sa.Column('signal_status', sa.Enum('PENDIENTE', 'ENTREGADA', 'MOSTRADA', 'EXPIRADA', 'SIN_SENAL', name='entrancesignalstatus', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('delivered_at', app.db.types.UTCDateTime(), nullable=True),
    sa.Column('acked_at', app.db.types.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['area_id'], ['areas.id'], name=op.f('fk_entrance_events_area_id_areas')),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], name=op.f('fk_entrance_events_device_id_devices')),
    sa.ForeignKeyConstraint(['engineer_id'], ['engineers.id'], name=op.f('fk_entrance_events_engineer_id_engineers')),
    sa.ForeignKeyConstraint(['qr_credential_id'], ['qr_credentials.id'], name=op.f('fk_entrance_events_qr_credential_id_qr_credentials')),
    sa.ForeignKeyConstraint(['request_id'], ['authorization_requests.id'], name=op.f('fk_entrance_events_request_id_authorization_requests')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_entrance_events'))
    )
    with op.batch_alter_table('entrance_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_entrance_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_entrance_events_device_id'), ['device_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_entrance_events_engineer_id'), ['engineer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_entrance_events_signal_status'), ['signal_status'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('entrance_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_entrance_events_signal_status'))
        batch_op.drop_index(batch_op.f('ix_entrance_events_engineer_id'))
        batch_op.drop_index(batch_op.f('ix_entrance_events_device_id'))
        batch_op.drop_index(batch_op.f('ix_entrance_events_created_at'))

    op.drop_table('entrance_events')
    with op.batch_alter_table('qr_credentials', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_qr_credentials_status'))
        batch_op.drop_index(batch_op.f('ix_qr_credentials_engineer_id'))

    op.drop_table('qr_credentials')
    with op.batch_alter_table('environment_readings', schema=None) as batch_op:
        batch_op.drop_index('ix_envreading_device_at')
        batch_op.drop_index(batch_op.f('ix_environment_readings_created_at'))

    op.drop_table('environment_readings')
