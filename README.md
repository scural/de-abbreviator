# de-abbreviator
An N-gram model specifically trained on USDA list of foods to de-abbreviate grocery items, specifically the way they are worded on receipts. Code was utilized in thesis project for class CP499. Heavily inspired by [@weirdMath's abbreviation spellchecker for english](https://github.com/avidale/weirdMath/blob/master/nlp/abbreviation_spellchecker_english.ipynb). 

# Usage
After running word_abb.py, user must plug in abbreaviated word inside alongside language models to get predicted word with the accuracy percentage. 
````
noisy_channel('cffe', big_lang_m, big_err_m)
````
````
{'coffee': 9.411900215724993}
````
