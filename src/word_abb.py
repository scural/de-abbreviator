"""
This file contains both data preprocessing as well as training n-grams models to de-abbreviate food items that can be found on receipts.
"""
"""
### GROCERY DATASET PREPROCESSING
"""

!pip install --user kaggle
import os
os.environ['KAGGLE_CONFIG_DIR'] = "/content"

!ls /content

!chmod 600 /content/kaggle.json

!kaggle datasets download -d heeraldedhia/groceries-dataset

!unzip /content/groceries-dataset.zip

dataset = open('/content/Groceries_dataset.csv', 'rt')

import csv
from io import StringIO

#Create a CSV reader
csv_reader = csv.reader(dataset)

#Iterate through each row in the CSV
parsed_groceries = ''
parsed_groceries_non = ''
unique_food_items = set()

for row in csv_reader:
    food_name = row[2]
    if food_name not in unique_food_items:
        parsed_groceries += food_name + ', '
        unique_food_items.add(food_name)


print(parsed_groceries)
grocery_list = parsed_groceries.split(', ')
print(len(grocery_list))

import pandas as pd

df = pd.read_csv('/content/food.csv', on_bad_lines='skip')
usda_foods = df['description'].drop_duplicates()

usda_string = usda_foods.to_string(index=False, header=False)
usda_string = ', '.join(usda_string.split())

for item in grocery_list:
  usda_string += item + ', '

print(usda_string)

"""### LANGUAGE MODELS FOR ABBREVIATION"""
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

class LanguageNgramModel:
    """
    The model remembers and predicts which letters follow which.
    Constructor parameters:
        order - number of characters the model remembers, or n-1
        smoothing - the number, added to each counter for stability
        recursive - weight of the model of one order less
    Learned parameters:
        counter_ - storage of n-grams, as dict of counters
        vocabulary_ - set of characters that the model knows
    """
    def __init__(self, order=1, smoothing=1.0, recursive=0.001):
        self.order = order
        self.smoothing = smoothing
        self.recursive = recursive
        self.push_to_hub = True

    def fit(self, corpus):
        """ Estimate freqency of all n-grams in the text
        parameters:
            corpus - a text string
        """
        self.counter_ = defaultdict(lambda: Counter())
        self.vocabulary_ = set()
        for i, token in enumerate(corpus[self.order:]):
            context = corpus[i:(i+self.order)]
            self.counter_[context][token] += 1
            self.vocabulary_.add(token)
        self.vocabulary_ = sorted(list(self.vocabulary_))
        if self.recursive > 0 and self.order > 0:
            self.child_ = LanguageNgramModel(self.order-1, self.smoothing, self.recursive)
            self.child_.fit(corpus)

    def get_counts(self, context):
        """ Estimate frequency of all symbols that may follow the context
        Parameters:
            context - text string (only the last self.order chars matter)
        Returns:
            freq - vector of letter conditional frequencies, as pandas.Series
        """
        if self.order:
            local = context[-self.order:]
        else:
            local = ''
        freq_dict = self.counter_[local]
        freq = pd.Series(index=self.vocabulary_, dtype='float64' )
        for i, token in enumerate(self.vocabulary_):
            freq[token] = freq_dict[token] + self.smoothing
        if self.recursive > 0 and self.order > 0:
            child_freq = self.child_.get_counts(context) * self.recursive
            freq += child_freq
        return freq

    def predict_proba(self, context):
        """ Estimate probability of all symbols that may follow the context
        Parameters:
            context - text string (only the last self.order chars matter)
        Returns:
            freq - vector of letter conditional frequencies, as pandas.Series
        """
        counts = self.get_counts(context)
        return counts / counts.sum()

    def single_log_proba(self, context, continuation):
        """ Estimate log probability of the certain continuation of the context
        Parameters:
            context - text string, known beginning of the phrase
            continuation - text string, its hypothetical end
        Returns:
            result - a float, log of probability
        """
        result = 0.0
        for token in continuation:
            result += np.log(self.predict_proba(context)[token])
            context += token
        return result

    def single_proba(self, context, continuation):
        """ Estimate probability of the certain continuation of the context
        Parameters:
            context - text string, known beginning of the phrase
            continuation - text string, its hypothetical end
        Returns:
            result - a float, probability
        """
        return np.exp(self.single_log_proba(context, continuation))

class MissingLetterModel:
    """
    The model remembers and predicts which letters are usually missed.
    Constructor parameters:
        order - number of characters the model remembers, or n-1
        smoothing_missed - the number added to missed counter
        smoothing_total - the number added to total counter
    Learned parameters:
        missed_counter_ - counter of occurences of the missed characters
        total_counter_ - counter of occurences of all characters
    """
    def __init__(self, order=0, smoothing_missed=0.3, smoothing_total=1.0):
        self.order = order
        self.smoothing_missed = smoothing_missed
        self.smoothing_total = smoothing_total

    def fit(self, sentence_pairs):
        """ Estimate of missing probability for each symbol
        Parameters:
            sentence_pairs - list of (original phrase, abbreviation)
        In the abbreviation, all missed symbols are replaced with "-"
        """
        self.missed_counter_ = defaultdict(lambda: Counter())
        self.total_counter_ = defaultdict(lambda: Counter())
        for (original, observed) in sentence_pairs:
            for i, (original_letter, observed_letter) \
                    in enumerate(zip(original[self.order:], observed[self.order:])):
                context = original[i:(i+self.order)]
                if observed_letter == '-':
                    self.missed_counter_[context][original_letter] += 1
                self.total_counter_[context][original_letter] += 1

    def predict_proba(self, context, last_letter):
        """ Estimate of probability of last_letter being missed after context"""
        if self.order:
            local = context[-self.order:]
        else:
            local = ''
        missed_freq = self.missed_counter_[local][last_letter] + self.smoothing_missed
        total_freq = self.total_counter_[local][last_letter] + self.smoothing_total
        return missed_freq / total_freq

    def single_log_proba(self, context, continuation, actual=None):
        """ Estimate log probability that after context,
            continuation is abbreviated to actual.
        If actual is None, it is assumed that nothing is abbreviated.
        """
        if not actual:
            actual = continuation
        result = 0.0
        for orig_token, act_token in zip(continuation, actual):
            pp = self.predict_proba(context, orig_token)
            if act_token != '-':
                pp = 1 - pp
            result += np.log(pp)
            context += orig_token
        return result

    def single_proba(self, context, continuation, actual=None):
        """ Estimate probability that after context,
            continuation is abbreviated to actual.
        If actual is None, it is assumed that nothing is abbreviated.
        """
        return np.exp(self.single_log_proba(context, continuation, actual))

from heapq import heappush, heappop
def generate_options(prefix_proba, prefix, suffix,
                     lang_model, missed_model, optimism=0.5, cache=None):
    """ Generate partial options of abbreviation decoding (a helper function)
    Parameters:
        prefix_proba - log probability of decoded part of the abbreviation
        prefix - decoded part of the abbreviation
        suffix - not decoded part of the abbreviation
        lang_model - the language model
        missed_model - the abbreviation probability model
        optimism - coefficient for log likelihood of the word end
        cache - storage of suffix likelihood estimates
    Returns: list of options in the form (likelihood estimate, decoded part,
        not decoded part, the new letter, the suffix likelihood estimate)
    """
    options = []
    for letter in lang_model.vocabulary_ + ['']:
        if letter:  # here we assume the character was missing
            next_letter = letter
            new_suffix = suffix
            new_prefix = prefix + next_letter
            proba_missing_state = - np.log(missed_model.predict_proba(prefix, letter))
        else:  # here we assume there was no missing character
            next_letter = suffix[0]
            new_suffix = suffix[1:]
            new_prefix = prefix + next_letter
            proba_missing_state = - np.log((1 - missed_model.predict_proba(prefix, next_letter)))
        proba_next_letter = - np.log(lang_model.single_proba(prefix, next_letter))
        if cache:
            proba_suffix = cache[len(new_suffix)] * optimism
        else:
            proba_suffix = - np.log(lang_model.single_proba(new_prefix, new_suffix)) * optimism
        proba = prefix_proba + proba_next_letter + proba_missing_state + proba_suffix
        options.append((proba, new_prefix, new_suffix, letter, proba_suffix))
    return options

def noisy_channel(word, lang_model, missed_model, freedom=3.0,
                  max_attempts=10000, optimism=0.9, verbose=False):
    """ Suggest phrases, for which word may be the abbreviation
    parameters:
        word - string, the abbreviation
        lang_model - the language model
        missed_model - the abbreviation probability model
        freedom - possible quality range of log likelihood of the candidates
        max_attempts - maximum number of iterations
        optimism - coefficient for log likelihood of the word end
        verbose - whether to print current candidates in the runtime
    returns: dict of keys - suggested phrases, and values -
        minus log likelihood of candidates
        The less this value, the more likely the suggestion
    """
    query = word + ' '
    prefix = ' '
    prefix_proba = 0.0
    suffix = query
    full_origin_logprob = -lang_model.single_log_proba(prefix, query)
    no_missing_logprob = -missed_model.single_log_proba(prefix, query)
    best_logprob = full_origin_logprob + no_missing_logprob
    # add an empty prefix to the heap
    heap = [(best_logprob * optimism, prefix, suffix, '', best_logprob * optimism)]
    # add the default candidate (without missing characters)
    candidates = [(best_logprob, prefix + query, '', None, 0.0)]
    if verbose:
        print('baseline score is', best_logprob)
    # prepare storage of the phrase suffix probabilities
    cache = {}
    for i in range(len(query)+1):
        future_suffix = query[:i]
        cache[len(future_suffix)] = -lang_model.single_log_proba('', future_suffix) # rough approximation
        cache[len(future_suffix)] += -missed_model.single_log_proba('', future_suffix) # at least add missingness

    for i in range(max_attempts):
        if not heap:
            break
        next_best = heappop(heap)
        if verbose:
            print(next_best)
        if next_best[2] == '':  # the phrase is fully decoded
            # if the phrase is good enough, add it to the answer
            if next_best[0] <= best_logprob + freedom:
                candidates.append(next_best)
                # update estimate of the best likelihood
                if next_best[0] < best_logprob:
                    best_logprob = next_best[0]
        else: # # the phrase is not fully decoded - generate more options
            prefix_proba = next_best[0] - next_best[4] # all proba estimate minus suffix
            prefix = next_best[1]
            suffix = next_best[2]
            new_options = generate_options(
                prefix_proba, prefix, suffix, lang_model,
                missed_model, optimism, cache)
            # add only the solution potentioally no worse than the best + freedom
            for new_option in new_options:
                if new_option[0] < best_logprob + freedom:
                    heappush(heap, new_option)
    if verbose:
        print('heap size is', len(heap), 'after', i, 'iterations')
    result = {}
    for candidate in candidates:
        if candidate[0] <= best_logprob + freedom:
            result[candidate[1][1:-1]] = candidate[0]
    return result

"""
### TRAINING MODELS AND TESTING
"""

import re
#Leave only letters and spaces in the text
parsed_groceries_2 = re.sub(r'[^a-z ]+', '', usda_string.lower().replace('\n', ' '))

all_letters = ''.join(list(sorted(list(set(parsed_groceries_2)))))
print(repr(all_letters)) # ' abcdefghijklmnopqrstuvwxyz'

# Prepare training sample for the abbreviation model
missing_set =  (
    [(all_letters, '-' * len(all_letters))] * 3 # all chars missing
    + [(all_letters, all_letters)] * 10 # all chars are NOT missing
    + [('aeiouy', '------')] * 30 # only vowels are missing
)
#Train both models
big_lang_m = LanguageNgramModel(order=4, smoothing=0.001, recursive=0.01)
big_lang_m.fit(parsed_groceries_2)
big_err_m = MissingLetterModel(order=0, smoothing_missed=0.1)
big_err_m.fit(missing_set)

for i in range(5):
    tmp = LanguageNgramModel(i, 0.001, 0.01)
    tmp.fit(parsed_groceries_2[0:-5000])
    print(i, tmp.single_log_proba(' ', parsed_groceries_2[-5000:]))

noisy_channel('appl', big_lang_m, big_err_m) #test to see if abb model works

noisy_channel('chckn', big_lang_m, big_err_m)

noisy_channel('frt juic', big_lang_m, big_err_m)

noisy_channel('buttr', big_lang_m, big_err_m)

noisy_channel('bgl', big_lang_m, big_err_m)

noisy_channel('cffe', big_lang_m, big_err_m)

noisy_channel('cinnmn', big_lang_m, big_err_m)

noisy_channel('hm', big_lang_m, big_err_m)


