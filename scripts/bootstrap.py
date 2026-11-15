"""Provision only this project's two local development schemas."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import required
from app.databases import sql_connection, oracle_connection


def quoted_password(name):
    # Generated setup passwords use only this alphabet; never interpolate user SQL.
    value = required(name)
    if not re.fullmatch(r'[A-Za-z0-9_!.-]{16,100}', value):
        raise ValueError('Use generated local passwords with the documented alphabet')
    return value


def setup_sql():
    password = quoted_password('SQLSERVER_PASSWORD')
    with sql_connection(admin=True, master=True) as c:
        q = c.cursor()
        q.execute("IF DB_ID('HealthcareIntegrationLab') IS NULL CREATE DATABASE HealthcareIntegrationLab")
        q.execute("SELECT 1 AS Present FROM sys.server_principals WHERE name='lab_app'")
        if not q.fetchone():
            q.execute("CREATE LOGIN lab_app WITH PASSWORD='" + password + "', CHECK_POLICY=ON")
    with sql_connection(admin=True) as c:
        q = c.cursor()
        q.execute("IF USER_ID('lab_app') IS NULL CREATE USER lab_app FOR LOGIN lab_app")
        q.execute("""IF OBJECT_ID('dbo.LabPatients','U') IS NULL CREATE TABLE dbo.LabPatients(
          PatientKey char(64) PRIMARY KEY, Manifest nvarchar(max) NOT NULL CHECK(ISJSON(Manifest)=1))""")
        q.execute("""IF OBJECT_ID('dbo.LabResources','U') IS NULL CREATE TABLE dbo.LabResources(
          PatientKey char(64) NOT NULL REFERENCES dbo.LabPatients(PatientKey),
          ResourceType varchar(40) NOT NULL, ResourceId varchar(120) NOT NULL,
          PayloadHash char(64) NOT NULL, Payload nvarchar(max) NOT NULL CHECK(ISJSON(Payload)=1),
          PRIMARY KEY(PatientKey,ResourceType,ResourceId))""")
        q.execute("""IF OBJECT_ID('dbo.LabCases','U') IS NULL CREATE TABLE dbo.LabCases(
          CaseId char(32) PRIMARY KEY, PatientKey char(64) NOT NULL REFERENCES dbo.LabPatients(PatientKey),
          Payload nvarchar(max) NOT NULL CHECK(ISJSON(Payload)=1),
          CreatedAt datetime2 NOT NULL DEFAULT SYSUTCDATETIME())""")
        for table in ('LabPatients', 'LabResources', 'LabCases'):
            q.execute(f'GRANT SELECT,INSERT,UPDATE,DELETE ON dbo.{table} TO lab_app')
        c.commit()


def setup_oracle():
    password = quoted_password('ORACLE_PASSWORD')
    with oracle_connection(admin=True) as c:
        q = c.cursor()
        # The official Free Lite image has no USERS tablespace. Keep this lab
        # separate from SYSTEM in its own small, non-growing data file.
        q.execute("SELECT COUNT(*) FROM DBA_TABLESPACES WHERE TABLESPACE_NAME='LAB_DATA'")
        if not q.fetchone()[0]:
            q.execute("CREATE TABLESPACE LAB_DATA DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/lab_data01.dbf' SIZE 32M AUTOEXTEND OFF")
        q.execute("SELECT COUNT(*) FROM ALL_USERS WHERE USERNAME='LAB_APP'")
        if not q.fetchone()[0]:
            q.execute('CREATE USER lab_app IDENTIFIED BY "' + password + '" DEFAULT TABLESPACE LAB_DATA QUOTA 32M ON LAB_DATA')
        q.execute('GRANT CREATE SESSION, CREATE TABLE TO lab_app')
    with oracle_connection() as c:
        q = c.cursor()
        q.execute("SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME='LAB_MIRROR'")
        if not q.fetchone()[0]:
            q.execute('''CREATE TABLE LAB_MIRROR(
              PATIENT_KEY VARCHAR2(64) NOT NULL, RESOURCE_TYPE VARCHAR2(40) NOT NULL,
              RESOURCE_ID VARCHAR2(120) NOT NULL, PAYLOAD_HASH VARCHAR2(64) NOT NULL,
              PAYLOAD CLOB NOT NULL CHECK (PAYLOAD IS JSON),
              PRIMARY KEY(PATIENT_KEY,RESOURCE_TYPE,RESOURCE_ID))''')
        c.commit()


if __name__ == '__main__':
    setup_sql(); print('SQL Server schema and application grants ready.')
    setup_oracle(); print('Oracle reporting schema ready.')
