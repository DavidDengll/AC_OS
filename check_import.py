try:
    import sentence_transformers
    print('sentence_transformers available')
except Exception as e:
    print('Import error:', e)