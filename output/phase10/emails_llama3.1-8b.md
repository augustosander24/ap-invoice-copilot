# Email drafts — communicator llama3.1:8b, as of 2026-11-30

## EX-001:P-106:buyer_query — send, paragraph model

```text
To: Sofia Ramos <sofia.ramos@northgate.example>
Subject: Your decision needed: invoice HIS-40817 from Harbor Industrial Supply

Hello Sofia,

You have an invoice from Harbor Industrial Supply with the number HIS-40817, which has a total of 3315.00. We have found issues with the price, which differs from the price on the purchase order. We need you to let us know whether to pay the billed price and update the purchase order, reject the invoice, or ask the vendor for a credit.

Invoice HIS-40817 from Harbor Industrial Supply, dated 2026-11-09, amount 3315.00. PO quoted: PO-26101.
Lines:
- line 1: IND-2210 Nitrile work gloves box of 100: 40 units at 28.50 each, line amount 1140.00
- line 2: IND-2415 Shop towel rolls case of 12: 60 units at 36.25 each, line amount 2175.00
Issues:
1. Price differs from the PO
   - tolerance limit 66.30 in dollars: the lower of 2% of the invoice amount 3315.00 (66.30) and the cap 100.00
   - line 2 IND-2415: invoice unit price 36.25, PO unit price 34.75, a difference of 1.50 per unit on 60 units billed: price variance 90.00 in dollars
   - total price variance 90.00 in dollars: over the tolerance limit 66.30
   Likely cause, from our review: The invoice line 2 (IND-2415) has a unit price of 36.25, which is higher than the PO line 2 price of 34.75, resulting in a price variance of 90.00. This exceeds the 2% tolerance limit of 66.30.
Action requested:
- Tell us whether to pay the billed price and update the PO, reject the invoice, or ask the vendor for a credit.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-002:P-107:buyer_query — send, paragraph model

```text
To: Tom Keller <tom.keller@northgate.example>
Subject: Your decision needed: invoice HIS-40852 from Harbor Industrial Supply

Hello Tom,

You have an invoice from Harbor Industrial Supply with the number HIS-40852, which has a total of 9201.00. We have found issues with the price, which differs from the price on the purchase order. We need you to tell us whether to pay the billed price and update the PO, reject the invoice, or ask the vendor for a credit.

Invoice HIS-40852 from Harbor Industrial Supply, dated 2026-11-12, amount 9201.00. PO quoted: PO-26102.
Lines:
- line 1: IND-3120 Heavy-duty pallet jack 2500 kg: 6 units at 785.00 each, line amount 4710.00
- line 2: IND-3305 Steel shelving unit 5-tier: 18 units at 249.50 each, line amount 4491.00
Issues:
1. Price differs from the PO
   - tolerance limit 100.00 in dollars: the lower of 2% of the invoice amount 9201.00 (184.02) and the cap 100.00
   - line 2 IND-3305: invoice unit price 249.50, PO unit price 242.00, a difference of 7.50 per unit on 18 units billed: price variance 135.00 in dollars
   - total price variance 135.00 in dollars: over the tolerance limit 100.00
   Likely cause, from our review: The invoice line 2 has a unit price of 249.50 for IND-3305, whereas the corresponding PO line 2 specifies a unit price of 242.00. This discrepancy between the agreed-upon PO price and the invoiced price caused the variance.
Action requested:
- Tell us whether to pay the billed price and update the PO, reject the invoice, or ask the vendor for a credit.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-003:V-1001:vendor_correction — send, paragraph model

```text
To: Harbor Industrial Supply <ar@harborindustrial.example>
Subject: Correction needed: invoice HIS-40903

Hello Harbor Industrial Supply accounts receivable team,

You have submitted an invoice, HIS-40903, with a total of 1404.00. However, we were unable to verify that the purchase order number provided is valid. We request that you send a corrected invoice that quotes a valid open purchase order number.

Invoice HIS-40903 from Harbor Industrial Supply, dated 2026-11-18, amount 1404.00. PO quoted: PO-26108.
Lines:
- line 1: IND-2630 Safety glasses clear lens box of 12: 30 units at 46.80 each, line amount 1404.00
Issues:
1. PO number can't be used
   - PO-26108 was not issued to Harbor Industrial Supply
Action requested:
- Send a corrected invoice that quotes a valid open purchase order number.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-004:P-106:buyer_query — send, paragraph model

```text
To: Sofia Ramos <sofia.ramos@northgate.example>
Subject: Your decision needed: invoice KF-23318 from Keystone Fasteners

Hello Sofia,

You have an invoice from Keystone Fasteners with the number KF-23318, which totals 4909.20. We have found issues with the billed quantity being more than received. We need you to tell us whether the missing quantity has arrived and the receipt is posted, or whether to reject the invoice or ask the vendor for a credit.

Invoice KF-23318 from Keystone Fasteners, dated 2026-11-06, amount 4909.20. PO quoted: PO-26103.
Lines:
- line 1: FAS-1050 Hex bolts M12 x 60 mm box of 250: 48 units at 62.90 each, line amount 3019.20
- line 2: FAS-1180 Stainless washers M12 box of 500: 100 units at 18.90 each, line amount 1890.00
Issues:
1. Billed quantity is more than received
   - tolerance limit 98.18 in dollars: the lower of 2% of the invoice amount 4909.20 (98.18) and the cap 100.00
   - line 2 FAS-1180: 100 units billed, 60 received, 40 not received; at the PO unit price 18.90 the units not received are a quantity variance of 756.00 in dollars
   - total quantity variance 756.00 in dollars: over the tolerance limit 98.18
   Likely cause, from our review: The quantity variance for line 2 (FAS-1180) arises because only 60 units were received (per receipt R-5007), while the invoice bills for 100 units. This short shipment of 40 units (60 received vs. 100 invoiced) caused the variance.
Action requested:
- Tell us whether the missing quantity has arrived and the receipt is posted, or whether to reject the invoice or ask the vendor for a credit.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-005:P-107:buyer_query — send, paragraph model

```text
To: Tom Keller <tom.keller@northgate.example>
Subject: Your decision needed: invoice KF-23342 from Keystone Fasteners

Hello Tom,

We have reviewed the invoice KF-23342 from Keystone Fasteners and have found two issues. The price on the invoice differs from the price on the purchase order, and the billed quantity is more than the quantity received. You are requested to inform us whether to pay the billed price and update the purchase order, reject the invoice, or ask the vendor for a credit, and also whether the missing quantity has arrived and the receipt is posted, or whether to reject the invoice or ask the vendor for a credit.

Invoice KF-23342 from Keystone Fasteners, dated 2026-11-16, amount 2182.50. PO quoted: PO-26104.
Lines:
- line 1: FAS-1265 Socket head cap screws M8 x 30 mm box of 500: 24 units at 41.25 each, line amount 990.00
- line 2: FAS-1390 Threaded rod M10 x 1 m: 150 units at 7.95 each, line amount 1192.50
Issues:
1. Price differs from the PO
   - tolerance limit 43.65 in dollars: the lower of 2% of the invoice amount 2182.50 (43.65) and the cap 100.00
   - line 2 FAS-1390: invoice unit price 7.95, PO unit price 7.60, a difference of 0.35 per unit on 150 units billed: price variance 52.50 in dollars
   - total price variance 52.50 in dollars: over the tolerance limit 43.65
   Likely cause, from our review: The invoice line 2 (FAS-1390) price of 7.95 exceeds the PO line 2 price of 7.60, creating a variance of 52.50.
2. Billed quantity is more than received
   - line 1 FAS-1265: 24 units billed, 0 received, 24 not received; at the PO unit price 41.25 the units not received are a quantity variance of 990.00 in dollars
   - line 2 FAS-1390: 150 units billed, 0 received, 150 not received; at the PO unit price 7.60 the units not received are a quantity variance of 1140.00 in dollars
   - total quantity variance 2130.00 in dollars: over the tolerance limit 43.65
   Likely cause, from our review: No goods were received for PO-26104 (the PO-26104 receipts shows 0 received for both lines), causing a 100% shortage of 24 and 150 units respectively.
Action requested:
- Tell us whether to pay the billed price and update the PO, reject the invoice, or ask the vendor for a credit.
- Tell us whether the missing quantity has arrived and the receipt is posted, or whether to reject the invoice or ask the vendor for a credit.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-006:V-1003:vendor_correction — send, paragraph model

```text
To: Summit Packaging <ar@summitpackaging.example>
Subject: Correction needed: invoice 009087

Hello Summit Packaging accounts receivable team,

You have submitted an invoice with the number 009087, which totals $2160.00. However, we were unable to verify that the purchase order number provided is valid. You are requested to send a corrected invoice that quotes a valid open purchase order number.

Invoice 009087 from Summit Packaging, dated 2026-11-02, amount 2160.00. PO quoted: PO-26105.
Lines:
- line 1: PKG-1210 Poly mailers 10x13 in case of 500: 45 units at 48.00 each, line amount 2160.00
Issues:
1. PO number can't be used
   - PO-26105 is closed
   Our open purchase order PO-26106 includes the item(s) on this invoice (PKG-1210). If that is the order you shipped against, please quote it.
Action requested:
- Send a corrected invoice that quotes a valid open purchase order number.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-007:V-1003:vendor_correction — send, paragraph model

```text
To: Summit Packaging <ar@summitpackaging.example>
Subject: Correction needed: invoice 009102

Hello Summit Packaging accounts receivable team,

You have submitted an invoice with the number 009102, which totals 6671.00. However, we have found an issue with the invoice, specifically that it does not include a purchase order number. We request that you send a corrected invoice that quotes the purchase order number.

Invoice 009102 from Summit Packaging, dated 2026-11-04, amount 6671.00. PO quoted: none.
Lines:
- line 1: PKG-1455 Kraft paper void fill 30 in x 1200 ft roll: 36 units at 54.25 each, line amount 1953.00
- line 2: PKG-1620 Carton sealing tape 2 in x 110 yd case of 36: 70 units at 67.40 each, line amount 4718.00
Issues:
1. No PO number on the invoice
   - this invoice quotes no purchase order number
   Our open purchase order PO-26107 includes the item(s) on this invoice (PKG-1455, PKG-1620). If that is the order you shipped against, please quote it.
Action requested:
- Send a corrected invoice that quotes the purchase order number.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-008:V-1003:vendor_correction — held (not_duplicate), paragraph model

```text
To: Summit Packaging <ar@summitpackaging.example>
Subject: Correction needed: invoice 8817

Hello Summit Packaging accounts receivable team,

You have submitted an invoice, invoice number 8817, with a total of 5352.00. However, we were unable to verify that the purchase order number provided is valid. You are requested to send a corrected invoice that quotes a valid open purchase order number.

Invoice 8817 from Summit Packaging, dated 2026-08-24, amount 5352.00. PO quoted: PO-26105.
Lines:
- line 1: PKG-1040 Corrugated shipping cartons 18x12x10 in bundle of 25: 120 units at 23.60 each, line amount 2832.00
- line 2: PKG-1125 Stretch wrap film 18 in x 1500 ft roll: 80 units at 31.50 each, line amount 2520.00
Issues:
1. PO number can't be used
   - PO-26105 is closed
Action requested:
- Send a corrected invoice that quotes a valid open purchase order number.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-008:V-1003:duplicate_notice — held (duplicate), paragraph model

```text
To: Summit Packaging <ar@summitpackaging.example>
Subject: Duplicate invoice: 8817

Hello Summit Packaging accounts receivable team,

You have submitted invoice number 8817 for a total of $5352.00. However, we have found that this invoice is a duplicate of a previously submitted invoice. We request that you confirm whether this is indeed a duplicate invoice so we can void it, or inform us if it is a separate charge.

Invoice 8817 from Summit Packaging, dated 2026-08-24, amount 5352.00. PO quoted: PO-26105.
Lines:
- line 1: PKG-1040 Corrugated shipping cartons 18x12x10 in bundle of 25: 120 units at 23.60 each, line amount 2832.00
- line 2: PKG-1125 Stretch wrap film 18 in x 1500 ft roll: 80 units at 31.50 each, line amount 2520.00
Issues:
1. Duplicate invoice
   - this invoice matches invoice 008817 dated 2026-08-24 for 5352.00, which we have already received and posted: the same purchase order (PO-26105) and the same invoice number once leading zeros and punctuation are dropped (8817 and 008817)
Action requested:
- Confirm that this invoice is a duplicate so we can void it, or tell us if it is a separate charge.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-009:P-107:buyer_query — send, paragraph model

```text
To: Tom Keller <tom.keller@northgate.example>
Subject: Your decision needed: invoice PEW-77104 from Pioneer Electrical Wholesale

Hello Tom,

You have an invoice from Pioneer Electrical Wholesale with the number PEW-77104, which has a total of 3010.00. We have found that the price on this invoice differs from the price on the purchase order. We need you to tell us whether to pay the billed price and update the purchase order, reject the invoice, or ask the vendor for a credit.

Invoice PEW-77104 from Pioneer Electrical Wholesale, dated 2026-11-20, amount 3010.00. PO quoted: PO-26108.
Lines:
- line 1: ELC-4075 THHN building wire 12 AWG 500 ft spool: 25 units at 124.00 each, line amount 3100.00
Issues:
1. Price differs from the PO
   - tolerance limit 60.20 in dollars: the lower of 2% of the invoice amount 3010.00 (60.20) and the cap 100.00
   - line 1 ELC-4075: invoice unit price 124.00, PO unit price 118.00, a difference of 6.00 per unit on 25 units billed: price variance 150.00 in dollars
   - total price variance 150.00 in dollars: over the tolerance limit 60.20
   Likely cause, from our review: The PO line PO-26108 line 1 specifies a unit price of 118.00 for ELC-4075, but the invoice line uses 124.00, creating a price variance of 150.00.
Action requested:
- Tell us whether to pay the billed price and update the PO, reject the invoice, or ask the vendor for a credit.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-009:V-1004:vendor_correction — send, paragraph model

```text
To: Pioneer Electrical Wholesale <ar@pioneerelectrical.example>
Subject: Correction needed: invoice PEW-77104

Hello Pioneer Electrical Wholesale accounts receivable team,

You have submitted an invoice, PEW-77104, with a total of 3010.00. However, we have found issues with the invoice details. You are requested to send a corrected invoice with the missing or incorrect details fixed.

Invoice PEW-77104 from Pioneer Electrical Wholesale, dated 2026-11-20, amount 3010.00. PO quoted: PO-26108.
Lines:
- line 1: ELC-4075 THHN building wire 12 AWG 500 ft spool: 25 units at 124.00 each, line amount 3100.00
Issues:
1. Missing or incorrect invoice details
   - header amount 3010.00 does not equal the lines total 3100.00
Action requested:
- Send a corrected invoice with the missing or incorrect details fixed.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-010:V-2001:duplicate_notice — send, paragraph model

```text
To: Riverside Power & Light <ar@riversidepower.example>
Subject: Duplicate invoice: RPL-104834

Hello Riverside Power & Light accounts receivable team,

You have submitted an invoice, RPL-104834, with a total of 4129.90. We have found that this invoice is a duplicate, and we are requesting confirmation from you regarding its status. Please let us know if this is indeed a duplicate invoice so we can void it, or if it is a separate charge.

Invoice RPL-104834 from Riverside Power & Light, dated 2026-10-28, amount 4129.90.
Service month: 2026-10
Lines:
- line 1: Electric service October 2026: amount 4129.90
Issues:
1. Duplicate invoice
   - this invoice has the same number as invoice RPL-104834 dated 2026-10-28 for 4129.90, which we have already received and posted
Action requested:
- Confirm that this invoice is a duplicate so we can void it, or tell us if it is a separate charge.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-012:P-109:approval_request — send, paragraph model

```text
To: Kevin Doyle <kevin.doyle@northgate.example>
Subject: Approval needed: invoice CWA-77324 from Clearwater Water Authority

Hello Kevin,

You are required to review invoice CWA-77324 from Clearwater Water Authority, which has a total of 1046.30. The bill differs from the vendor's average bill by more than 10%, and approval is needed.

Invoice CWA-77324 from Clearwater Water Authority, dated 2026-11-28, amount 1046.30.
Service month: 2026-11
Cost center: Facilities (CC-200)
GL account: 6100
Lines:
- line 1: Water and sewer service November 2026: amount 1046.30
Issues:
1. Approval needed
   - bill 15: average of the last 12 bills is 859.19; 1046.30 is +21.78%, over 10%
   - approver P-109: owner of CC-200
   - GL 6100 from category utilities
   From our review: This bill (1046.30) is 21.78% higher than the average of the last 12 bills (859.19), exceeding the 10% threshold. Previous bills ranged from 827.95 to 889.35 (e.g., CWA-77310: 862.40, CWA-77323: 843.60).
Action requested:
- Approve or reject this invoice.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-013:V-2003:vendor_correction — send, paragraph model

```text
To: GreenCycle Waste Services <ar@greencyclewaste.example>
Subject: Correction needed: invoice GCW-0043

Hello GreenCycle Waste Services accounts receivable team,

You have submitted an invoice, GCW-0043, with an invoice total of 646.20. However, we have found issues with the missing or incorrect invoice details. We request that you send a corrected invoice with the missing or incorrect details fixed.

Invoice GCW-0043 from GreenCycle Waste Services, dated 2026-11-28, amount 646.20.
Lines:
- line 1: Waste and recycling collection: amount 646.20
Issues:
1. Missing or incorrect invoice details
   - the service month is missing
Action requested:
- Send a corrected invoice with the missing or incorrect details fixed.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-013:P-108:approval_request — send, paragraph model

```text
To: Laura Mendes <laura.mendes@northgate.example>
Subject: Approval needed: invoice GCW-0043 from GreenCycle Waste Services

Hello Laura,

You are required to approve invoice GCW-0043 from GreenCycle Waste Services, which totals 646.20. This is bill 3 from a new utility vendor, and the first 3 bills always need approval. Approval is needed.

Invoice GCW-0043 from GreenCycle Waste Services, dated 2026-11-28, amount 646.20.
Cost center: Warehouse Operations (CC-100)
GL account: 6100
Lines:
- line 1: Waste and recycling collection: amount 646.20
Issues:
1. Approval needed
   - bill 3 from this vendor: the first 3 bills always need approval
   - approver P-108: owner of CC-100
   - GL 6100 from category utilities
   From our review: This is the third bill from this vendor (bill_count: 2 in history, this is GCW-0043), which requires approval. The amount (646.20) is slightly lower than the previous bill (GCW-0042: 651.75) but follows the same utility service pattern.
Action requested:
- Approve or reject this invoice.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-014:P-108:approval_request — send, paragraph model

```text
To: Laura Mendes <laura.mendes@northgate.example>
Subject: Approval needed: invoice LIP-2026-11 from Lakeside Industrial Properties

Hello Laura,

You are required to review invoice LIP-2026-11 from Lakeside Industrial Properties, which has a total of 19425.00. The invoice requires approval due to the rent billed differing from the lease amount. You are requested to either approve or reject this invoice.

Invoice LIP-2026-11 from Lakeside Industrial Properties, dated 2026-11-01, amount 19425.00.
Service month: 2026-11
Cost center: Warehouse Operations (CC-100)
GL account: 6200
Lines:
- line 1: Warehouse base rent November 2026: amount 18500.00
- line 2: Late payment fee: amount 925.00
Issues:
1. Approval needed
   - lease 18500.00, billed 19425.00, difference 925.00
   - approver P-108: owner of CC-100
   - GL 6200 from category rent
   From our review: The difference of 925.00 is due to a late payment fee, as the lease amount from the vendor record is 18500.00 and the invoice includes an additional 925.00 for the late fee.
Action requested:
- Approve or reject this invoice.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-016:P-102:approval_request — send, paragraph model

```text
To: Daniel Ortiz <daniel.ortiz@northgate.example>
Subject: Approval needed: invoice MCT-2026-H2 from Marlow County Treasurer

Hello Daniel,

You are required to approve invoice MCT-2026-H2 from Marlow County Treasurer, which totals 9850.00. Approval is needed for this invoice as tax bills always require approval. You are requested to either approve or reject this invoice.

Invoice MCT-2026-H2 from Marlow County Treasurer, dated 2026-11-02, amount 9850.00.
Service month: 2026-11
Cost center: Finance (CC-400)
GL account: 6300
Lines:
- line 1: Real property tax second half 2026: amount 9850.00
Issues:
1. Approval needed
   - taxes always need approval
   - approver P-102: owner of CC-400
   - GL 6300 from category taxes
Action requested:
- Approve or reject this invoice.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-017:P-102:approval_request — send, paragraph model

```text
To: Daniel Ortiz <daniel.ortiz@northgate.example>
Subject: Approval needed: invoice CL-88210 from CloudLedger Software

Hello Daniel,

You are required to approve invoice CL-88210 from CloudLedger Software, which totals 1450.00. This invoice requires approval as subscription bills always need approval. You are requested to either approve or reject this invoice.

Invoice CL-88210 from CloudLedger Software, dated 2026-11-01, amount 1450.00.
Service month: 2026-11
Cost center: Finance (CC-400)
GL account: 6400
Lines:
- line 1: CloudLedger Enterprise plan November 2026: amount 1450.00
Issues:
1. Approval needed
   - subscriptions always need approval
   - approver P-102: owner of CC-400
   - GL 6400 from category subscriptions
Action requested:
- Approve or reject this invoice.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-018:P-110:approval_request — send, paragraph model

```text
To: Priya Nair <priya.nair@northgate.example>
Subject: Approval needed: invoice RW-3317 from RouteWise Logistics Software

Hello Priya,

You are required to approve invoice RW-3317 from RouteWise Logistics Software, which totals 3740.00. This invoice requires approval as subscription bills always need approval. You are requested to either approve or reject this invoice.

Invoice RW-3317 from RouteWise Logistics Software, dated 2026-11-01, amount 3740.00.
Service month: 2026-11
Cost center: Information Technology (CC-300)
GL account: 6400
Lines:
- line 1: RouteWise Pro plan November 2026: amount 780.00
- line 2: Rugged handheld barcode scanners 8 units: amount 2960.00
Issues:
1. Approval needed
   - subscriptions always need approval
   - approver P-110: owner of CC-300
   - GL 6400 from category subscriptions
Action requested:
- Approve or reject this invoice.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-019:P-102:service_confirmation — send, paragraph model

```text
To: Daniel Ortiz <daniel.ortiz@northgate.example>
Subject: Please confirm the service: invoice BC-2026-041 from Bennett & Cole CPAs

Hello Daniel,

You have an invoice from Bennett & Cole CPAs with the number BC-2026-041 for a total of 7500.00. We have found an issue with the invoice, which is that service confirmation is needed. We approve a professional services invoice only after the requester confirms the service.

Invoice BC-2026-041 from Bennett & Cole CPAs, dated 2026-11-20, amount 7500.00.
Cost center: Finance (CC-400)
GL account: 6500
Requester: Daniel Ortiz
Lines:
- line 1: Year-end audit planning phase 1: amount 7500.00
Issues:
1. Service confirmation needed
   - professional services need a requester confirmation, then approval
Action requested:
- Confirm that the service was received, or tell us what is wrong.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-019:P-101:approval_request — waiting (confirmation), paragraph model

```text
To: Margaret Hale <margaret.hale@northgate.example>
Subject: Approval needed: invoice BC-2026-041 from Bennett & Cole CPAs

Hello Margaret,

You are required to approve or reject invoice BC-2026-041 from Bennett & Cole CPAs, which totals 7500.00. This invoice requires approval because professional services always need approval, and this request goes to you only after the requester of the service has confirmed it was received. Approval is needed.

Invoice BC-2026-041 from Bennett & Cole CPAs, dated 2026-11-20, amount 7500.00.
Cost center: Finance (CC-400)
GL account: 6500
Requester: Daniel Ortiz
Lines:
- line 1: Year-end audit planning phase 1: amount 7500.00
Issues:
1. Approval needed
   - professional services need a requester confirmation, then approval
   - approver P-101: requester P-102 owns CC-400, so approval goes to their manager
   - GL 6500 from category professional_services
Action requested:
- Approve or reject this invoice.
Reply by: set when this email is sent, after the service confirmation

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-020:P-112:service_confirmation — send, paragraph model

```text
To: Hannah Cho <hannah.cho@northgate.example>
Subject: Please confirm the service: invoice IBC-1233 from Ironbridge IT Consulting

Hello Hannah,

You have an invoice from Ironbridge IT Consulting with the number IBC-1233, which totals 4860.00. We have found an issue with this invoice, specifically that service confirmation is needed. This is because we approve a professional services invoice only after the requester confirms the service.

Invoice IBC-1233 from Ironbridge IT Consulting, dated 2026-11-23, amount 4860.00.
Cost center: Information Technology (CC-300)
GL account: 6500
Requester: Hannah Cho
Lines:
- line 1: Firewall upgrade project completed November 20 2026: amount 4860.00
Issues:
1. Service confirmation needed
   - professional services need a requester confirmation, then approval
Action requested:
- Confirm that the service was received, or tell us what is wrong.
Reply by: 2026-12-03

Accounts Payable
Northgate Distribution
ap@northgate.example
```

## EX-020:P-110:approval_request — waiting (confirmation), paragraph model

```text
To: Priya Nair <priya.nair@northgate.example>
Subject: Approval needed: invoice IBC-1233 from Ironbridge IT Consulting

Hello Priya,

You are required to approve invoice IBC-1233 from Ironbridge IT Consulting, which totals 4860.00. This invoice requires approval as professional services always need approval, and this request goes to you only after the requester of the service has confirmed it was received. You are requested to approve or reject this invoice.

Invoice IBC-1233 from Ironbridge IT Consulting, dated 2026-11-23, amount 4860.00.
Cost center: Information Technology (CC-300)
GL account: 6500
Requester: Hannah Cho
Lines:
- line 1: Firewall upgrade project completed November 20 2026: amount 4860.00
Issues:
1. Approval needed
   - professional services need a requester confirmation, then approval
   - approver P-110: owner of CC-300
   - GL 6500 from category professional_services
Action requested:
- Approve or reject this invoice.
Reply by: set when this email is sent, after the service confirmation

Accounts Payable
Northgate Distribution
ap@northgate.example
```
