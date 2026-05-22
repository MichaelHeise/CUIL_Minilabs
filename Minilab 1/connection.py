import asyncio
import httpx
import argparse

HTTP_11 = "1.1"
HTTP_2 = "2"

async def send_http_request(host, port, path, HTTP_version=HTTP_11):
    http_1 = HTTP_version == HTTP_11
    http_2 = HTTP_version == HTTP_2
    async with httpx.AsyncClient(http1=http_1, http2=http_2) as client:
        response = await client.get(f"http://{host}:{port}{path}")
        print(f"{response.http_version} {response.status_code} {response.reason_phrase}")
        print("Headers:")
        for header, value in response.headers.items():
            print(f"  {header}: {value}")
        print(f"Response Data: {response.text}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="cuil.internet-transparency.org", help="Host to connect to")
    parser.add_argument("--port", type=int, default=80, help="Port to connect to")
    parser.add_argument("--path", default="/index.html", help="Path to request")
    parser.add_argument("--http_version", choices=[HTTP_11, HTTP_2], default=HTTP_11, help="HTTP version to use (1.1 or 2)")
    args = parser.parse_args()
    asyncio.run(send_http_request(args.host, args.port, args.path, args.http_version))