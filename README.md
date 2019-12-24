# A GraphQL Python Client Library - gqlclient

This client library is largely derived from [py-graphql-client](https://github.com/ecthiender/py-graphql-client) and [python-graphql-client](https://github.com/ecthiender/py-graphql-client). It consolidates and improves the key functionalities provided by the aforementioned libraries, making code integration task a bit easier.

## Install dependencies
```
pip3 install -r requirements.txt
```

## Example
```python
from graphqlclient import GraphQLClient, GraphQLSubscriptionClient

client = GraphQLClient('http://localhost:8082/query')
subscription = GraphQLSubscriptionClient('ws://localhost:8082/query')

def callback(data):
  print(f"customer {data['payload']['data']['id']} says {data['payload']['data']['message']}")

gql_query = '''
  {
    allCustomers {
      id
      name
    }
  }
'''

gql_sub = '''
  subscription {
    customerNotification {
      id
      message
    }
  }
'''

result = client.execute(gql_query)
subscription_id = subscription.subscribe(gql_sub, callback=callback)
print(f"query result is {json.loads(result)['data']}")


# At the end of subscription

subscription.close()
```
## Permit self-signed certificates
```python
client = GraphQLClient('https://localhost:8082/query',certcheck=False)
```