import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from app.db.mongo import db

async def main():
    await db.connect()
    
    cursor = db.db['raw_materials'].find({}, {'_id': 1, 'commonName': 1, 'activePercentage': 1,
                                              'bandUpperCushion': 1, 'bandLowerCushion': 1, 'formulas': 1})
    docs = await cursor.to_list(10)
    
    for doc in docs:
        rm_id = str(doc.get('_id'))
        name = doc.get('commonName')
        formulas = doc.get('formulas', [])
        pct = doc.get('activePercentage')
        upper = doc.get('bandUpperCushion')
        lower = doc.get('bandLowerCushion')
        print(f"Raw Material: {name} (id={rm_id})")
        print(f"  active={pct}%, upper={upper}, lower={lower}")
        print(f"  Formulas: {len(formulas)}")
        for f in formulas:
            salt = f.get('salToInhibit')
            is_range = f.get('applicableIonicStrength')
            formula = f.get('formulaForInhibitionPerformance', '')
            print(f"    salt={salt}, IS={is_range}")
            print(f"    formula={formula[:80]}")
        print()
    
    await db.disconnect()

asyncio.run(main())
