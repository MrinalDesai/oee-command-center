import os, time, snowflake.connector as sc
c = sc.connect(account=os.environ['SNOWFLAKE_ACCOUNT'], user=os.environ['SNOWFLAKE_USER'],
               password=os.environ['SNOWFLAKE_PASSWORD'], role='ACCOUNTADMIN')
cur = c.cursor()
print(cur.execute("PUT 'file://C:/dev/oee-command-center/forgepulse-ui/spec.yml' @OEE_DB.CONTAINERS.SERVICE_SPECS AUTO_COMPRESS=FALSE OVERWRITE=TRUE").fetchone())
print(cur.execute("ALTER SERVICE OEE_DB.CONTAINERS.FORGEPULSE_CONSOLE FROM @OEE_DB.CONTAINERS.SERVICE_SPECS SPECIFICATION_FILE='spec.yml'").fetchone())
for i in range(30):
    st = cur.execute("SELECT SYSTEM$GET_SERVICE_STATUS('OEE_DB.CONTAINERS.FORGEPULSE_CONSOLE')").fetchone()[0]
    print(i, st, flush=True)
    if 'READY' in st:
        break
    time.sleep(10)
c.close()
