import os, snowflake.connector as sc
c = sc.connect(account=os.environ['SNOWFLAKE_ACCOUNT'], user=os.environ['SNOWFLAKE_USER'],
               private_key_file=os.path.expanduser('~/.snowflake/rsa_key.p8'), role='ACCOUNTADMIN')
print(c.cursor().execute("CALL SYSTEM$GET_SERVICE_LOGS('OEE_DB.CONTAINERS.FORGEPULSE_CONSOLE', 0, 'console', 200)").fetchone()[0])
c.close()

