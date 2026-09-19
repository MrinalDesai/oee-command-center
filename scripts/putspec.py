import os, snowflake.connector as sc
c = sc.connect(account=os.environ['SNOWFLAKE_ACCOUNT'], user=os.environ['SNOWFLAKE_USER'],
               password=os.environ['SNOWFLAKE_PASSWORD'], role='ACCOUNTADMIN')
cur = c.cursor()
print(cur.execute("PUT 'file://C:/dev/oee-command-center/forgepulse-ui/spec.yml' @OEE_DB.CONTAINERS.SERVICE_SPECS AUTO_COMPRESS=FALSE OVERWRITE=TRUE").fetchone())
print(cur.execute("LIST @OEE_DB.CONTAINERS.SERVICE_SPECS").fetchall())
print('POOL:', cur.execute('DESCRIBE COMPUTE POOL OEE_UI_POOL').fetchone()[1])
c.close()
