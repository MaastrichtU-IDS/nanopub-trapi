from SPARQLWrapper import SPARQLWrapper, POST, JSON
import urllib.request, json 

get_nanopubs_select_query = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX np: <http://www.nanopub.org/nschema#>
PREFIX npx: <http://purl.org/nanopub/x/>
SELECT DISTINCT *
WHERE {
  graph ?np_assertion {
    ?association
      rdf:subject ?subject ;
      rdf:predicate ?predicate ;
      rdf:object ?object .
    OPTIONAL {
      ?association biolink:relation ?relation .
    }
    OPTIONAL {
      ?association biolink:provided_by ?provided_by .
    }
    OPTIONAL {
      ?association biolink:association_type ?association_type .
    }
  }
  ?subject biolink:category ?subject_category .
  ?object biolink:category ?object_category .
  ?_entity_filters
  graph ?np_head {
    ?np_uri np:hasAssertion ?np_assertion .
  }
  FILTER NOT EXISTS { ?creator npx:retracts ?np_uri }
}"""

get_predicates_select_query = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX np: <http://www.nanopub.org/nschema#>
PREFIX npx: <http://purl.org/nanopub/x/>
SELECT DISTINCT ?subject_category ?predicate_category ?object_category
WHERE {
  graph ?np_assertion {
    ?association
      rdf:subject ?subject ;
      rdf:predicate ?predicate_category ;
      rdf:object ?object .
  }
  ?subject biolink:category ?subject_category .
  ?object biolink:category ?object_category .
  graph ?np_head {
    ?np_uri np:hasAssertion ?np_assertion .
  }
  FILTER NOT EXISTS { ?creator npx:retracts ?np_uri }
}"""

## Virtuoso SPARQL endpoint for the Nanopubs server at IDS
SPARQL_ENDPOINT_URL = 'http://virtuoso.np.dumontierlab.137.120.31.101.nip.io/sparql'

## Load BioLink JSON-LD Context to resolve URIs to BioLink CURIEs
with urllib.request.urlopen("https://raw.githubusercontent.com/biolink/biolink-model/master/context.jsonld") as url:
    data = json.loads(url.read().decode())
    
namespace_resolver = {}
context = data['@context']
for prefix in context.keys():
    if isinstance(context[prefix], str):
        namespace_resolver[prefix] = context[prefix]

uri_resolver = {v: k for k, v in namespace_resolver.items()}
uri_resolver['https://identifiers.org/mim/'] = 'OMIM'
uri_resolver['https://identifiers.org/drugbank/'] = 'DRUGBANK'
uri_resolver['https://w3id.org/biolink/'] = 'biolink'

def resolve_uri_with_context(uri_string):
    """Take an URI and return its CURIE form, using the BioLink JSON-LD Context previously loaded
    """
    for prefix in namespace_resolver.keys():
        if uri_string.startswith(namespace_resolver[prefix]):
            return uri_string.replace(namespace_resolver[prefix], prefix + ':')

    return uri_string

def get_predicates_from_nanopubs():
    """Query the Nanopublications network to get BioLink entity categories and the relation between them
    Formatted for the Translator TRAPI /predicate get call
    """
    predicates = {}
    # Run query to get types and relations between them
    sparql = SPARQLWrapper(SPARQL_ENDPOINT_URL)
    sparql.setReturnFormat(JSON)
    sparql.setQuery(get_predicates_select_query)
    sparqlwrapper_results = sparql.query().convert()
    sparql_results = sparqlwrapper_results["results"]["bindings"]
    for result in sparql_results:
        np_subject = resolve_uri_with_context(result['subject_category']['value'])
        np_predicate = resolve_uri_with_context(result['predicate_category']['value'])
        np_object = resolve_uri_with_context(result['object_category']['value'])
        if not predicates.get(np_subject):
            predicates[np_subject] = {}

        if not predicates[np_subject].get(np_object):
            predicates[np_subject][np_object] = []
        if not np_predicate in predicates[np_subject][np_object]:
            predicates[np_subject][np_object].append(np_predicate)

    return predicates

def reasonerapi_to_sparql(reasoner_query):
    """Convert an array of predictions objects to ReasonerAPI format
    Run the get_predict to get the QueryGraph edges and nodes
    {disease: OMIM:1567, drug: DRUGBANK:DB0001, score: 0.9}

    :param: reasoner_query Query from Reasoner API
    :return: Results as ReasonerAPI object
    """
    query_graph = reasoner_query["message"]["query_graph"]
    query_options = {}
    n_results = None
    if 'query_options' in reasoner_query.keys():
        query_options = reasoner_query["query_options"]
        if 'n_results' in query_options:
            n_results = int(query_options["n_results"])

    if len(query_graph["edges"]) != 1:
        return {'error': len(query_graph["edges"]) + """ edges have been provided. 
            This API currently only implements 1 hop queries (with 1 edge query_graph). 
            Contact us if you are interested in running multiple hop queries"""}
    
    sparql_query_get_nanopubs = get_nanopubs_select_query
    predicate_category = ''
    subject_category = ''
    object_category = ''
    predicate_edge_id = ''
    subject_node_id = ''
    object_node_id = ''
    # TODO: improve to support multiple edges query (aka. hops)
    for edge_id in query_graph['edges'].keys():
        edge_props = query_graph['edges'][edge_id]
        predicate_edge_id = edge_id
        subject_node_id = edge_props['subject']
        object_node_id = edge_props['object']
        # predicate_category = edge_props['predicate']
        # subject_category = query_graph['nodes'][edge_props['subject']]['category']
        # object_category = query_graph['nodes'][edge_props['object']]['category']
        # sparql_query_get_nanopubs = sparql_query_get_nanopubs.replace('?_predicate_category', predicate_category)
        # sparql_query_get_nanopubs = sparql_query_get_nanopubs.replace('?_subject_category', subject_category)
        # sparql_query_get_nanopubs = sparql_query_get_nanopubs.replace('?_object_category', object_category)
        
        entity_filters = ''
        try:
          predicate_uri = edge_props['predicate']
          entity_filters = entity_filters + 'FILTER (?predicate = ' + predicate_uri + ')\n'
        except:
          pass

        try:
          subject_category = query_graph['nodes'][edge_props['subject']]['category']
          entity_filters = entity_filters + 'FILTER (?subject_category = ' + subject_category + ')\n'
        except:
          pass

        try:
          object_category = query_graph['nodes'][edge_props['object']]['category']
          entity_filters = entity_filters + 'FILTER (?object_category = ' + object_category + ')\n'
        except:
          pass

        # TODO: currently only accepting URIs, improve for CURIEs
        try:
          subject_curie = query_graph['nodes'][edge_props['subject']]['curie']
          entity_filters = entity_filters + 'FILTER (?subject = <' + subject_curie + '>)\n'
        except:
          pass
        try:
          object_curie = query_graph['nodes'][edge_props['object']]['curie']
          entity_filters = entity_filters + 'FILTER (?object = <' + object_curie + '>)\n'
        except:
          pass
        sparql_query_get_nanopubs = sparql_query_get_nanopubs.replace('?_entity_filters', entity_filters)

    # Add LIMIT to the SPARQL query if n_results provided
    if n_results:
        sparql_query_get_nanopubs = sparql_query_get_nanopubs + ' LIMIT ' + str(n_results)

    knowledge_graph = {'nodes': {}, 'edges': {}}
    query_results = []
    kg_edge_count = 0

    print('Running the following SPARQL query to retrieve nanopublications from ' + SPARQL_ENDPOINT_URL)
    print(sparql_query_get_nanopubs)
    sparql = SPARQLWrapper(SPARQL_ENDPOINT_URL)
    sparql.setReturnFormat(JSON)
    sparql.setQuery(sparql_query_get_nanopubs)
    sparqlwrapper_results = sparql.query().convert()
    sparql_results = sparqlwrapper_results["results"]["bindings"]

    # Check current official example of Reasoner query results: https://github.com/NCATSTranslator/ReasonerAPI/blob/master/examples/Message/simple.json
    # Now iterates the Nanopubs SPARQL query results:
    for edge_result in sparql_results:
        edge_uri = edge_result['association']['value']
        # Create edge object in knowledge_graph
        knowledge_graph['edges'][edge_uri] = {
            'predicate': resolve_uri_with_context(edge_result['predicate']['value']),
            'subject': resolve_uri_with_context(edge_result['subject']['value']),
            'object': resolve_uri_with_context(edge_result['object']['value'])
        }
        if edge_result['relation']:
          knowledge_graph['edges'][edge_uri]['relation'] = resolve_uri_with_context(edge_result['relation']['value'])
        # if edge_result['association_type']:
        #   knowledge_graph['edges'][edge_uri]['association_type'] = resolve_uri_with_context(edge_result['association_type']['value'])

        attributes_obj = {}
        if edge_result['provided_by']:
          attributes_obj['provided_by'] = resolve_uri_with_context(edge_result['provided_by']['value'])

        if len(attributes_obj) > 0:
          knowledge_graph['edges'][edge_uri]['attributes'] = attributes_obj

        knowledge_graph['nodes'][edge_result['subject']['value']] = {
            'category': resolve_uri_with_context(edge_result['subject_category']['value'])
        }
        knowledge_graph['nodes'][edge_result['object']['value']] = {
            'category': resolve_uri_with_context(edge_result['object_category']['value'])
        }

        # Add the bindings to the results object
        result = {'edge_bindings': {}, 'node_bindings': {}}
        result['edge_bindings'][predicate_edge_id] = [
            {
                "id": edge_uri
            }
        ]
        result['node_bindings'][subject_node_id] = [
            {
                "id": edge_result['subject']['value']
            }
        ]
        result['node_bindings'][object_node_id] = [
            {
                "id": edge_result['object']['value']
            }
        ]
        query_results.append(result)

        kg_edge_count += 1
    
    return {'message': {'knowledge_graph': knowledge_graph, 'query_graph': query_graph, 'results': query_results}}