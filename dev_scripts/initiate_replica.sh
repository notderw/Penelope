#!/bin/bash

echo "Starting replica set initialize"
until mongo --host mongo -u ${MONGO_USERNAME} -p ${MONGO_PASSWORD} --eval "print(\"waited for connection\")"
do
    sleep 2
done
echo "Connection finished"
echo "Creating replica set"
mongo --host mongo -u ${MONGO_USERNAME} -p ${MONGO_PASSWORD} <<EOF
rs.initiate(
    {
        _id : 'rs0',
        members: [
            { _id : 0, host : "mongo:27017" }
        ]
    }
)
EOF
echo "replica set created"
