import os, time, snowflake.connector as sc
c = sc.connect(account=os.environ['SNOWFLAKE_ACCOUNT'], user=os.environ['SNOWFLAKE_USER'],
               private_key_file=os.path.expanduser('~/.snowflake/rsa_key.p8'), role='ACCOUNTADMIN')
cur = c.cursor()
for i in range(40):
    st = cur.execute("SELECT SYSTEM$GET_SERVICE_STATUS('OEE_DB.CONTAINERS.FORGEPULSE_CONSOLE')").fetchone()[0]
    print(i, st, flush=True)
    if 'READY' in st:
        break
    time.sleep(15)
print(cur.execute('SHOW ENDPOINTS IN SERVICE OEE_DB.CONTAINERS.FORGEPULSE_CONSOLE').fetchall())
c.close()

