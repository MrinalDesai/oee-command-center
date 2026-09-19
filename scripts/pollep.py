import os, time, snowflake.connector as sc
c = sc.connect(account=os.environ['SNOWFLAKE_ACCOUNT'], user=os.environ['SNOWFLAKE_USER'],
               password=os.environ['SNOWFLAKE_PASSWORD'], role='ACCOUNTADMIN')
cur = c.cursor()
for i in range(40):
    row = cur.execute('SHOW ENDPOINTS IN SERVICE OEE_DB.CONTAINERS.FORGEPULSE_CONSOLE').fetchall()[0]
    print(i, row[5], flush=True)
    if 'provisioning' not in str(row[5]).lower():
        break
    time.sleep(20)
c.close()
