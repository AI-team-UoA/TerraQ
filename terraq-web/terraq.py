from flask import Flask, render_template, request, jsonify, send_file
from requests.auth import HTTPBasicAuth
import requests
import random
import io
import argparse

app = Flask(__name__)

QA_SERVER = ""
KG_ENDPOINT = ""
USERNAME = ""
PASSWORD = ""


def graphdb_send_request(endpoint_url, query, accept_format='application/sparql-results+json'):
    """
    Sends a SPARQL query to a GraphDB endpoint.

    :param endpoint_url: URL of the GraphDB SPARQL endpoint
    :param query: SPARQL query to be sent
    :param accept_format: Desired response format (default is JSON)
    :return: Response from the endpoint
    """
    headers = {
        'Accept': accept_format,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'query': query
    }

    response = requests.post(endpoint_url, headers=headers, data=data, auth=HTTPBasicAuth(USERNAME, PASSWORD))

    if response.status_code == 200:
        flat_results = []
        json_response = response.json()
        for result in json_response['results']['bindings']:
            for binding in result.values():
                flat_results.append(binding['value'])
        return flat_results
    else:
        response.raise_for_status()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/app', methods=['GET', 'POST'])
def app_page():
    if request.method == 'POST':
        question = request.form.get('question')
        response = requests.post(QA_SERVER + '/startquestionansweringwithtextquestion', json={"question": question})
        response_payload = response.json()  # Assuming the endpoint returns a list of URIs
        sparql_query = response_payload['query']
        uris = graphdb_send_request(KG_ENDPOINT, sparql_query)
        
        print(len(uris))
        random.shuffle(uris)
        
        # Limit answer to 50 tuples
        if len(uris) > 50:
            uris = uris[:50]
        
        uris = list(map((lambda x: x.replace("http://ai.di.uoa.gr/da4dte/resource/", "")), uris))
        print(uris)
        
        return render_template('app.html', question=question, uris=uris)
    return render_template('app.html', uris=[])

@app.route('/get_wkt_thumbnail', methods=['POST'])
def get_wkt_thumbnail():
    uri = "http://ai.di.uoa.gr/da4dte/resource/" + request.json.get('uri')
    wkt_response = requests.post(QA_SERVER + '/wkt', json={"uri": uri})
    thumbnail_response = requests.post(QA_SERVER + '/thumbnail', json={"uri": uri})
    return jsonify({
        "wkt": wkt_response.text.replace("<http://www.opengis.net/def/crs/EPSG/0/4326>", ""),  # Assuming it returns the WKT string
        "thumbnail": thumbnail_response.text  # Assuming it returns a URL or base64 image
    })
    
@app.route("/image-metadata", methods=["GET"])
def image_metadata():
    s1_metadata_query = """
    SELECT ?time ?productType ?orbitNumber ?processingLevel WHERE 
    {{ 
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasTimestamp> ?time .
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasProductType> ?productType .
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasOrbitNumber> ?orbitNumber .
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasProcessingLevel> ?processingLevel .
    }}
    """
    
    s2_metadata_query = """
    SELECT ?time ?productType ?cloudCoverage ?vegetationCoverage ?snowIcePercentage WHERE 
    {{ 
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasTimestamp> ?time .
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasProductType> ?productType .
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasCloudCover> ?cloudCoverage .
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasVegetationPercentage> ?vegetationCoverage .
        <{uri}> <http://ai.di.uoa.gr/da4dte/ontology/hasSnowIcePercentage> ?snowIcePercentage .
    }}
    """
    
    uri = request.args.get("uri")
    
    if not uri:
        return jsonify({"error": "Missing 'uri' parameter"}), 400
    
    sentinel1 = uri[1] == '1'
    
    uri = "http://ai.di.uoa.gr/da4dte/resource/" + uri
    
    print(s1_metadata_query)
    print(s1_metadata_query.format(uri=uri))
    
    if (sentinel1):
        # get Sentinel-1 metadata
        metadata = graphdb_send_request(KG_ENDPOINT, s1_metadata_query.format(uri=uri))
        metadata = {
            "timestamp": metadata[0],
            "productType": metadata[1],
            "orbitNumber": metadata[2],
            "processingLevel": metadata[3],
        }
    else:
        # get Sentinel-2 metadata
        metadata = graphdb_send_request(KG_ENDPOINT, s2_metadata_query.format(uri=uri))
        metadata = {
            "timestamp": metadata[0],
            "productType": metadata[1],
            "cloudCoverage": metadata[2],
            "vegetationCoverage": metadata[3],
            "snowIcePercentage": metadata[4],
        }

    return jsonify(metadata)

@app.route("/suggestion", methods=["GET"])
def suggestion():
    suggestions = [
        "Give me 50 images of rivers in Finland.",
        "I want 3 images with vegetation percentage over 80%.",
        "Give me images with snow coverage over 2%.",
        "Find 12 sentinel-2 images with cloud coverage over 15% and vegetation percentage less than 10%.",
        "Give me 3 pictures of rivers in Italy with vegetation coverage over 20% after May 2020.",
        "Give me 3 pictures of rivers and ports with vegetation coverage over 20% taken in 2020.",
        "Give me 10 sentinel images with orbit number 22113.",
        "Give me pictures of Italy in a span of 3 days.",
        "sentinel-1 pictures after 10/10/2012 but before 11/15/2023.",
        "Find Sentinel-2 images in France with cloud coverage less than 10% acquired after March 2020.",
        "Find 10 images of Piedmont with cloud coverage under 20% and more than 50% vegetation taken in August 2022.",
        "Show me 20 images of the Adriatic sea.",
        "Show me sentinel-1 images of Helsinki with vertical vertical polarisation.",
        "Show me the image of Athens with the highest cloud coverage taken in July 2022.",
        "Give me 10 images with more than 10% snow coverage in Belgium."
    ]
    return random.choice(suggestions)

@app.route('/download-image', methods=['POST'])
def download_image():
    try:
        # Get the image URL from the frontend
        data = request.json
        image_url = data.get('image_url')

        if not image_url:
            return jsonify({'error': 'No image URL provided'}), 400

        # Fetch the image from the URL
        response = requests.get(image_url, stream=True)

        if response.status_code == 200:
            # Create an in-memory file to store the image
            img_data = io.BytesIO(response.content)
            img_data.seek(0)

            # Serve the image as a file download
            return send_file(
                img_data,
                mimetype=response.headers.get('Content-Type', 'image/jpeg'),
                as_attachment=True,
                download_name='downloaded-image.jpg'
            )
        else:
            return jsonify({'error': f'Failed to fetch image. Status code: {response.status_code}'}), response.status_code

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    parser = argparse.ArgumentParser("terraq")
    parser.add_argument("QA_SERVER", help="The IP address and port of the TerraQ question-answering pipeline.", type=str)
    parser.add_argument("KG_ENDPOINT", help="The endpoint of the RDF store that holds the Knowledge Graph.", type=str)
    parser.add_argument("USERNAME", help="RDF store authentication username.", type=str)
    parser.add_argument("PASSWORD", help="RDF store authentication password.", type=str)
    
    args = parser.parse_args()
    QA_SERVER = vars(args)['QA_SERVER']
    KG_ENDPOINT = vars(args)['KG_ENDPOINT']
    USERNAME = vars(args)['USERNAME']
    PASSWORD = vars(args)['PASSWORD']
    
    app.run(debug=True, port=10000)
