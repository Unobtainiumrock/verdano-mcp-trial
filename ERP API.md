# Verdano Trial ERP API

You have access to a small mock ERP API for Verdano Foods. The API is intentionally simple: it knows Verdano's products, customers, warehouses, inventory, open orders, and order drafts. It does not know how retailer spreadsheets map to those concepts.

The base URL is `https://erp.corvera.ai`

Authenticate every ERP request with:

```
Authorization: Bearer <your_api_key>
```

There is no OpenAPI page. Use the endpoint list below.

## Endpoints

### `GET /health`

Returns service status. No auth required.

### `GET /erp/products`

Returns Verdano's product master. Important fields include:

- `sku`: internal ERP SKU.
- `name`: internal product name.
- `case_pack`: consumer units per case.
- `current_gtins` and `legacy_gtins`: product barcodes known by the ERP.
- `aliases`: names the ERP knows but does not treat as primary.
- `temperature_band`: useful for warehouse/ship-to selection.

### `GET /erp/customers`

Returns customer and location records. The ERP separates:

- `sold_to`: commercial customer.
- `bill_to`: legal billing entity.
- `ship_to`: delivery location.

### `GET /erp/warehouses`

Returns warehouse ids and temperature bands.

### `GET /erp/inventory`

Optional query params: `sku`, `warehouse_id`.

Returns available and allocated cases by SKU and warehouse.

### `GET /erp/open-orders`

Optional query params: `retailer`, `sku`. `retailer` accepts a case-insensitive substring of the sold-to customer name, e.g. `tesco` or `sainsbury`.

Returns current ERP sales orders. These are already committed and should be considered when assessing demand.

### `POST /erp/order-drafts`

Creates a draft sales order.

Request shape:

```json
{
  "external_reference": "your-unique-reference",
  "sold_to_customer_id": "CUST-TESCO-UK",
  "bill_to_customer_id": "BILL-TESCO-HQ",
  "ship_to_location_id": "SHIP-TESCO-DAV",
  "required_date": "2026-05-13",
  "lines": [
    {
      "sku": "VG-FALA-500",
      "quantity_cases": 8
    }
  ],
  "notes": "Optional note"
}
```

The endpoint validates customer types, parent relationships, known SKUs, positive quantities, and ship-to warehouse temperature compatibility. Reusing the same `external_reference` returns the existing draft.

### `GET /erp/order-drafts`

Returns order drafts created with your API key.
