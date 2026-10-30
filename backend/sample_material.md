# Python Lists and Loops

A list in Python is an ordered collection of items. Lists are created with square brackets, and items are separated by commas. A list can hold items of different types, such as numbers and strings.

Every item in a list has an index. Indexing starts at 0, so the first item is at index 0 and the second item is at index 1. A negative index counts from the end, so index -1 refers to the last item.

Lists are mutable, which means you can change them after they are created. The append() method adds a new item at the end of the list. The remove() method deletes the first item that matches a given value.

```python
fruits = ["apple", "banana", "cherry"]
fruits.append("mango")
fruits.remove("banana")
print(fruits[0])
print(fruits[-1])
print(len(fruits))
```

The len() function returns the number of items in a list. Slicing lets you take a part of a list. The slice fruits[0:2] returns items from index 0 up to, but not including, index 2.

A for loop visits each item of a list one by one. The loop variable takes the value of the current item on every pass. The range() function produces a sequence of numbers, and range(3) gives 0, 1 and 2.

```python
total = 0
for n in [2, 4, 6]:
    total = total + n
print(total)
```

A while loop repeats as long as its condition is True. If the condition never becomes False, the loop runs forever, which is called an infinite loop.
