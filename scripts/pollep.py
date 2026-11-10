import os, time, snowflake.connector as sc
c = sc.connect(account=os.environ['SNOWFLAKE_ACCOUNT'], user=os.environ['SNOWFLAKE_USER'],
               private_key_file=os.path.expanduser('~/.snowflake/rsa_key.p8'), role='ACCOUNTADMIN')
cur = c.cursor()
for i in range(40):
    row = cur.execute('SHOW ENDPOINTS IN SERVICE OEE_DB.CONTAINERS.FORGEPULSE_CONSOLE').fetchall()[0]
    print(i, row[5], flush=True)
    if 'provisioning' not in str(row[5]).lower():
        break
    time.sleep(20)
c.close()

