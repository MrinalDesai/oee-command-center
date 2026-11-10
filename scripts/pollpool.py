import os, time, snowflake.connector as sc
c = sc.connect(account=os.environ['SNOWFLAKE_ACCOUNT'], user=os.environ['SNOWFLAKE_USER'],
               private_key_file=os.path.expanduser('~/.snowflake/rsa_key.p8'), role='ACCOUNTADMIN')
cur = c.cursor()
for i in range(40):
    state = cur.execute('DESCRIBE COMPUTE POOL OEE_UI_POOL').fetchone()[1]
    print(i, state, flush=True)
    if state in ('ACTIVE', 'IDLE'):
        break
    time.sleep(15)
c.close()

